"""Local grouped photo evidence and a reviewed inventory projection.

This module never decodes images, calls a provider, performs OCR or executes a model.
It accepts human observations; byte integrity is not image-content verification.
Optional OCR receipts are reviewed separately through photo_ocr_flow.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

APP_ID = "ideaforge"
RESULT_FORMAT = APP_ID + ".reviewed-photo-inventory.v1"
STORE_FORMAT = APP_ID + ".photo-inventory-store.v1"
MAX_IMAGE = 1024 * 1024
MAX_TOTAL_IMAGES = 32 * 1024 * 1024
MAX_STATE = 256 * 1024
MAX_ITEMS, MAX_PHOTOS, MAX_HISTORY, MAX_REVISIONS = 16, 6, 32, 128
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SUBJECTS = {"module", "carrier", "developer_kit", "unknown"}
NVIDIA_ORIN = "https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/index.html"
NVIDIA_BRINGUP = ("https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/"
                 "HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html")
NVIDIA_NANO = "https://developer.nvidia.com/embedded/dlc/jetson_nano_developer_kit_user_guide"
# Reviewed paraphrases only, no manufacturer images or document reproduction.
CATALOG = {
    "P3767-0000": ("module", "Jetson Orin NX 16GB", NVIDIA_ORIN, "35.3.1 GA; updated 2023-05-19", "Devices Supported by This Document"),
    "P3767-0001": ("module", "Jetson Orin NX 8GB", NVIDIA_ORIN, "35.3.1 GA; updated 2023-05-19", "Devices Supported by This Document"),
    "P3767-0003": ("module", "Jetson Orin Nano 8GB", NVIDIA_ORIN, "35.3.1 GA; updated 2023-05-19", "Devices Supported by This Document"),
    "P3767-0004": ("module", "Jetson Orin Nano 4GB", NVIDIA_ORIN, "35.3.1 GA; updated 2023-05-19", "Devices Supported by This Document"),
    "P3767-0005": ("module", "Jetson Orin Nano 8GB with SD card slot", NVIDIA_ORIN, "35.3.1 GA; updated 2023-05-19", "Devices Supported by This Document"),
    "P3768-0000": ("carrier", "Jetson Orin Nano reference carrier", NVIDIA_BRINGUP, "35.3.1", "Porting the Linux Kernel Device Tree Files"),
    "P3448-0000": ("module", "Jetson Nano developer-kit module", NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "P3449-0000": ("carrier", "Jetson Nano reference carrier", NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "945-13450-0000-100": ("developer_kit", "Jetson Nano developer kit with B01 carrier", NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "945-13450-0000-000": ("developer_kit", "Jetson Nano developer kit with A02 carrier", NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
}


class PhotoEvidenceError(ValueError):
    pass


def _keys(obj, names):
    if type(obj) is not dict or set(obj) != set(names):
        raise PhotoEvidenceError("Missing or unknown object fields")


def _string(value, maximum=240, *, empty=False):
    if type(value) is not str or (not value and not empty):
        raise PhotoEvidenceError("Expected a bounded string")
    try:
        if len(value.encode("utf-8")) > maximum or "\x00" in value:
            raise PhotoEvidenceError("String exceeds limit or contains NUL")
    except UnicodeError as exc:
        raise PhotoEvidenceError("Invalid Unicode") from exc
    return value


def _id(value):
    if type(value) is not str or not ID.fullmatch(value):
        raise PhotoEvidenceError("Invalid portable ID")
    return value


def _choice(value, options):
    if type(value) is not str or value not in options:
        raise PhotoEvidenceError("Invalid enum string")
    return value


def _hash(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise PhotoEvidenceError("Invalid SHA256")
    return value


def _positive(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise PhotoEvidenceError("Invalid positive integer")
    return value


def _json_bytes(value):
    try:
        raw = (json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    except (ValueError, UnicodeError, TypeError) as exc:
        raise PhotoEvidenceError("Invalid JSON value") from exc
    if len(raw) > MAX_STATE:
        raise PhotoEvidenceError("JSON exceeds byte limit")
    return raw


def _decode(raw):
    if len(raw) > MAX_STATE:
        raise PhotoEvidenceError("JSON exceeds byte limit")
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise PhotoEvidenceError("Duplicate JSON key")
            obj[key] = value
        return obj
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(PhotoEvidenceError("Nonfinite JSON")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PhotoEvidenceError("Invalid strict UTF-8 JSON") from exc
    def visit(value, depth=0):
        if depth > 12:
            raise PhotoEvidenceError("JSON depth limit")
        if type(value) is dict:
            for key, child in value.items():
                _string(key)
                visit(child, depth + 1)
        elif type(value) is list:
            if len(value) > 128:
                raise PhotoEvidenceError("JSON array limit")
            for child in value:
                visit(child, depth + 1)
        elif type(value) is str:
            _string(value, 2048, empty=True)
        elif value is not None and type(value) not in (bool, int):
            raise PhotoEvidenceError("Unsupported JSON scalar")
    visit(obj)
    return obj


def _safe(path):
    path = Path(path).absolute()
    if str(path).startswith(("\\\\", "//")):
        raise PhotoEvidenceError("Network paths are unsupported")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PhotoEvidenceError("Symlink/reparse paths are unsupported")
    return path


def _read(path, maximum):
    path = _safe(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= maximum:
            raise PhotoEvidenceError("File type, hardlink or byte limit")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(maximum + 1)
        after = os.fstat(fd)
        current = path.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if len(raw) != before.st_size or signature(before) != signature(after) or signature(after) != signature(current):
            raise PhotoEvidenceError("File changed during read")
        _safe(path)
        return raw
    finally:
        os.close(fd)


def _atomic(path, raw):
    path = _safe(path)
    fd, name = tempfile.mkstemp(prefix="write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _safe(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _media(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise PhotoEvidenceError("Expected PNG/JPEG/WebP container signature; no image decoder is used")


def _scope(scope, shared):
    if type(scope) is not str or scope not in {"project", "equipment"}:
        raise PhotoEvidenceError("Invalid sharing scope")
    if type(shared) is not list or len(shared) > 16 or len(set(map(_id, shared))) != len(shared):
        raise PhotoEvidenceError("Invalid explicit shared project IDs")
    if scope == "project" and shared:
        raise PhotoEvidenceError("Project-only items cannot be shared")


def _observations(observations, photos):
    if type(observations) is not list or len(observations) > 32:
        raise PhotoEvidenceError("Observation count limit")
    available = {p["sha256"] for p in photos}
    for row in observations:
        _keys(row, {"photo_sha256", "subject", "kind", "visibility", "text"})
        if _hash(row["photo_sha256"]) not in available:
            raise PhotoEvidenceError("Observation refers to another photo")
        _choice(row["subject"], SUBJECTS)
        _choice(row["kind"], {"model_code", "label", "port"})
        _choice(row["visibility"], {"clear", "blurred", "missing"})
        _string(row["text"], 240, empty=True)
        if row["visibility"] == "clear" and not row["text"]:
            raise PhotoEvidenceError("Clear observations require text")


def _evaluate_manual(item):
    """Match exact human-transcribed public codes; never inspect image pixels."""
    review = item["review"]
    codes, conflicts, unresolved = {}, [], 0
    if review:
        for observation in review["observations"]:
            if observation["kind"] != "model_code" or observation["visibility"] != "clear":
                continue
            code = observation["text"].strip().upper()
            if code not in CATALOG:
                unresolved += 1
                continue
            subject, name, url, revision, locator = CATALOG[code]
            if observation["subject"] != subject:
                conflicts.append("Public model code was assigned to the wrong component kind")
                continue
            codes.setdefault(subject, {})[code] = {
                "code": code, "name": name, "manufacturer": "NVIDIA", "subject": subject,
                "source_url": url, "source_revision": revision, "source_locator": locator,
                "document_sha256": None, "evidence": "human-transcribed exact public code",
                "hardware_revision": "unknown",
            }
    if any(len(options) > 1 for options in codes.values()):
        conflicts.append("Different clear model codes identify the same component kind")
    identities = {subject: list(options.values())[0] for subject, options in codes.items() if len(options) == 1}
    # A carrier/module pair never implies kit, RAM or component revision.
    required = ({"module", "carrier"} if review and review["expected_subject"] == "assembly"
                else {review["expected_subject"]} if review else set())
    resolved = bool(required) and "unknown" not in required and required <= set(identities)
    confirmed = bool(review and review["confirm_identity"] and item["quantity"] is not None and resolved and not conflicts and not unresolved)
    follow_up = (
        "Photograph the full module model/part-number label sharply, then the carrier underside part/revision label; mask serial numbers. "
        "For developer-kit identity, include its box part-number label. Confirm that all views are of this one grouped item and confirm quantity."
    )
    return {"status": "conflicting" if conflicts else "reviewed" if confirmed else "provisional",
            "identities": identities, "conflicts": sorted(set(conflicts)),
            "confidence": "human-reviewed-public-code-match" if identities and not conflicts and not unresolved else "unknown",
            "unresolved_model_code_count": unresolved,
            "follow_up": None if confirmed else follow_up, "recognition": "unavailable"}


def _review_sha256(item):
    """Bind human and OCR review state without changing their attribution."""
    context = {key: copy.deepcopy(item.get(key)) for key in (
        "review", "ocr_review", "quantity", "quantity_reviewer", "ownership",
        "scope", "shared_with")}
    return hashlib.sha256(_json_bytes(context)).hexdigest()


def evaluate(item):
    """Combine reviewed evidence; diagnostic OCR confidence never proves identity."""
    manual = _evaluate_manual(item)
    ocr = item.get("ocr_review")
    if ocr is None:
        return manual
    summary = ocr["summary"]
    identities = copy.deepcopy(manual["identities"])
    conflicts = list(manual["conflicts"]) + list(summary["conflicts"])
    for subject, identity in summary["identities"].items():
        if subject in identities and identities[subject]["code"] != identity["code"]:
            conflicts.append("Human and OCR reviewed public codes conflict")
            identities.pop(subject, None)
        elif subject not in identities:
            identities[subject] = copy.deepcopy(identity)
    unresolved = manual["unresolved_model_code_count"] + summary["unresolved_model_code_count"]
    required = ({"module", "carrier"} if ocr["expected_subject"] == "assembly"
                else {ocr["expected_subject"]})
    resolved = "unknown" not in required and required <= set(identities)
    confirmed = bool(ocr["confirm_identity"] and item["quantity"] is not None
                     and resolved and not conflicts and not unresolved)
    return {"status": "conflicting" if conflicts else "reviewed" if confirmed else "provisional",
            "identities": identities, "conflicts": sorted(set(conflicts)),
            "confidence": "human-reviewed-ocr-public-code-match" if confirmed else "unknown",
            "unresolved_model_code_count": unresolved,
            "follow_up": None if confirmed else (manual["follow_up"] or
                "Capture readable full public part codes and review every component kind; identity is provisional."),
            "recognition": "test-only-reviewed-ocr" if ocr["test_only"] else "local-ocr-human-reviewed"}


class PhotoLedger:
    """One app/project-bound local store. Single writer; no network or native jobs."""

    def __init__(self, root, project_id):
        self.root = _safe(root)
        self.project_id = _id(project_id)
        self.binding = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        for child in ("images", "versions"):
            target = _safe(self.root / child)
            target.mkdir(exist_ok=True)
        self.head = self.root / "head.json"
        if not self.head.exists():
            self._commit({"format": STORE_FORMAT, "app_id": APP_ID,
                          "project_id": project_id, "root_binding": self.binding,
                          "revision": 0, "items": []}, initialize=True)
        self._load()

    def _validate(self, state):
        _keys(state, {"format", "app_id", "project_id", "root_binding", "revision", "items"})
        if (state["format"], state["app_id"], state["project_id"], state["root_binding"]) != (
                STORE_FORMAT, APP_ID, self.project_id, self.binding):
            raise PhotoEvidenceError("App/project/store binding mismatch")
        _positive(state["revision"], MAX_REVISIONS)
        if type(state["items"]) is not list or len(state["items"]) > MAX_ITEMS:
            raise PhotoEvidenceError("Item count limit")
        ids, all_hashes, total = set(), set(), 0
        for item in state["items"]:
            if type(item) is not dict:
                raise PhotoEvidenceError("Inventory item must be an object")
            _keys(item, {"item_id", "scope", "shared_with", "quantity", "quantity_reviewer", "ownership", "photos", "review", "history"} | ({"ocr_review"} if "ocr_review" in item else set()))
            if _id(item["item_id"]) in ids:
                raise PhotoEvidenceError("Duplicate item ID")
            ids.add(item["item_id"])
            _scope(item["scope"], item["shared_with"])
            if item["quantity"] is not None:
                _positive(item["quantity"], 10000)
                _string(item["quantity_reviewer"])
            elif item["quantity_reviewer"] is not None:
                raise PhotoEvidenceError("Quantity reviewer without quantity")
            if type(item["photos"]) is not list or not 1 <= len(item["photos"]) <= MAX_PHOTOS:
                raise PhotoEvidenceError("Photo count limit")
            for photo in item["photos"]:
                _keys(photo, {"sha256", "bytes", "media_type"})
                digest = _hash(photo["sha256"])
                if digest in all_hashes:
                    raise PhotoEvidenceError("Duplicate photo across item groups")
                all_hashes.add(digest)
                total += _positive(photo["bytes"], MAX_IMAGE)
                _choice(photo["media_type"], {"image/png", "image/jpeg", "image/webp"})
            _choice(item["ownership"], {"unknown", "owned", "borrowed"})
            review = item["review"]
            if review is not None:
                _keys(review, {"reviewer", "expected_subject", "confirm_identity", "observations"})
                _string(review["reviewer"])
                _choice(review["expected_subject"], SUBJECTS | {"assembly"})
                if type(review["confirm_identity"]) is not bool:
                    raise PhotoEvidenceError("Invalid identity review")
                _observations(review["observations"], item["photos"])
            if item.get("ocr_review") is not None:
                from .photo_ocr_flow import validate_stored_review
                validate_stored_review(self, item, item["ocr_review"], state["revision"])
            if type(item["history"]) is not list or not 1 <= len(item["history"]) <= MAX_HISTORY:
                raise PhotoEvidenceError("History limit")
            for event in item["history"]:
                if type(event) is not dict:
                    raise PhotoEvidenceError("Inventory history event must be an object")
                _keys(event, {"event", "reviewer", "time_ns", "prior_review", "prior_quantity", "prior_ownership", "prior_scope", "prior_shared_with", "prior_photos"} | ({"prior_ocr_review"} if "prior_ocr_review" in event else set())
                      | ({"prior_quantity_reviewer"} if "prior_quantity_reviewer" in event else set()))
                _choice(event["event"], {"intake", "review", "quantity", "sharing", "ocr_review", "ocr_clear", "ocr_undo"})
                if event["event"] in {"ocr_review", "ocr_clear", "ocr_undo"} and "prior_quantity_reviewer" not in event:
                    raise PhotoEvidenceError("OCR history requires prior quantity reviewer attribution")
                _string(event["reviewer"])
                _positive(event["time_ns"], 10**30)
                if event["prior_quantity"] is not None:
                    _positive(event["prior_quantity"], 10000)
                if "prior_quantity_reviewer" in event:
                    if event["prior_quantity"] is None:
                        if event["prior_quantity_reviewer"] is not None:
                            raise PhotoEvidenceError("Prior quantity reviewer without quantity")
                    else:
                        _string(event["prior_quantity_reviewer"])
                _choice(event["prior_ownership"], {"unknown", "owned", "borrowed"})
                _scope(event["prior_scope"], event["prior_shared_with"])
                if type(event["prior_photos"]) is not list or len(event["prior_photos"]) > MAX_PHOTOS:
                    raise PhotoEvidenceError("Invalid prior photo list")
                for photo in event["prior_photos"]:
                    _keys(photo, {"sha256", "bytes", "media_type"})
                    if photo not in item["photos"]:
                        raise PhotoEvidenceError("Invalid prior photo binding")
                if event.get("prior_ocr_review") is not None:
                    from .photo_ocr_flow import validate_stored_review
                    prior_item = {"item_id": item["item_id"], "photos": event["prior_photos"]}
                    validate_stored_review(self, prior_item, event["prior_ocr_review"], state["revision"])
                prior = event["prior_review"]
                if prior is not None:
                    _keys(prior, {"reviewer", "expected_subject", "confirm_identity", "observations"})
                    _string(prior["reviewer"])
                    _choice(prior["expected_subject"], SUBJECTS | {"assembly"})
                    if type(prior["confirm_identity"]) is not bool:
                        raise PhotoEvidenceError("Invalid prior review")
                    _observations(prior["observations"], item["photos"])
        if total > MAX_TOTAL_IMAGES:
            raise PhotoEvidenceError("Total photo byte limit")

    def _layout_budget(self):
        total, counts = 0, {}
        for directory, maximum in (("images", MAX_ITEMS * MAX_PHOTOS), ("versions", MAX_REVISIONS)):
            count = 0
            with os.scandir(_safe(self.root / directory)) as entries:
                for entry in entries:
                    count += 1
                    if count > maximum:
                        raise PhotoEvidenceError("Store directory count limit")
                    path = _safe(entry.path)
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise PhotoEvidenceError("Invalid store entry")
                    if directory == "images":
                        if not re.fullmatch(r"[0-9a-f]{64}\.bin", entry.name) or not 1 <= info.st_size <= MAX_IMAGE:
                            raise PhotoEvidenceError("Invalid image store entry")
                        total += info.st_size
                    elif (not re.fullmatch(r"[1-9][0-9]{0,2}\.json", entry.name)
                          or not 1 <= int(entry.name[:-5]) <= MAX_REVISIONS
                          or not 1 <= info.st_size <= MAX_STATE):
                        raise PhotoEvidenceError("Invalid version store entry")
            counts[directory] = count
        if total > MAX_TOTAL_IMAGES:
            raise PhotoEvidenceError("Stored image byte budget exceeded")
        from .photo_ocr_flow import receipt_budget
        receipt_budget(self)
        return {"bytes": total, "images": counts["images"], "versions": counts["versions"]}

    def _load(self):
        self._layout_budget()
        head = _decode(_read(self.head, 2048))
        _keys(head, {"format", "revision", "state_sha256"})
        if head["format"] != STORE_FORMAT:
            raise PhotoEvidenceError("Invalid head format")
        revision = _positive(head["revision"], MAX_REVISIONS)
        digest = _hash(head["state_sha256"])
        raw = _read(self.root / "versions" / (str(revision) + ".json"), MAX_STATE)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise PhotoEvidenceError("Tampered ledger snapshot")
        state = _decode(raw)
        self._validate(state)
        if state["revision"] != revision:
            raise PhotoEvidenceError("Revision mismatch")
        for item in state["items"]:
            for photo in item["photos"]:
                raw = _read(self.root / "images" / (photo["sha256"] + ".bin"), MAX_IMAGE)
                if len(raw) != photo["bytes"] or hashlib.sha256(raw).hexdigest() != photo["sha256"] or _media(raw) != photo["media_type"]:
                    raise PhotoEvidenceError("Tampered original image")
        return state

    @contextmanager
    def _writer(self):
        lock = _safe(self.root / "write-lock")
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise PhotoEvidenceError("Writer lock exists; inspect it manually before retry") from exc
        try:
            yield
        finally:
            lock.rmdir()

    def _commit(self, state, *, initialize=False):
        with self._writer():
            return self._publish_locked(state, initialize=initialize)

    def _publish_locked(self, state, *, initialize=False):
        """Caller holds _writer across all evidence writes and publication."""
        if not initialize:
            current = self._load()
            if current["revision"] != state["revision"]:
                raise PhotoEvidenceError("Concurrent revision changed; retry explicitly")
        elif self.head.exists():
            raise PhotoEvidenceError("Store was already initialized")
        state, snapshot, raw = self._prepare_next(state)
        _atomic(snapshot, raw)
        _atomic(self.head, _json_bytes({"format": STORE_FORMAT, "revision": state["revision"],
                                      "state_sha256": hashlib.sha256(raw).hexdigest()}))
        return state

    def _prepare_next(self, state):
        state = copy.deepcopy(state)
        state["revision"] += 1
        self._validate(state)
        snapshot = _safe(self.root / "versions" / (str(state["revision"]) + ".json"))
        if snapshot.exists():
            raise PhotoEvidenceError("Existing revision requires manual recovery")
        budget = self._layout_budget()
        if budget["versions"] >= MAX_REVISIONS:
            raise PhotoEvidenceError("Version count limit")
        return state, snapshot, _json_bytes(state)

    @staticmethod
    def _event(item, kind, reviewer):
        if len(item["history"]) >= MAX_HISTORY:
            raise PhotoEvidenceError("History limit; preserve store and create a reviewed archive")
        item["history"].append({"event": kind, "reviewer": _string(reviewer),
                                "time_ns": time.time_ns(), "prior_review": copy.deepcopy(item["review"]),
                                "prior_quantity": item["quantity"], "prior_quantity_reviewer": item["quantity_reviewer"],
                                "prior_ownership": item["ownership"],
                                "prior_scope": item["scope"], "prior_shared_with": copy.deepcopy(item["shared_with"]),
                                "prior_photos": copy.deepcopy(item["photos"])})
        if "ocr_review" in item:
            item["history"][-1]["prior_ocr_review"] = copy.deepcopy(item["ocr_review"])

    def intake(self, item_id, image_paths, *, reviewer, same_item_confirmed, scope="project", shared_with=None):
        with self._writer():
            return self._intake_locked(item_id, image_paths, reviewer=reviewer,
                                       same_item_confirmed=same_item_confirmed, scope=scope, shared_with=shared_with)

    def _intake_locked(self, item_id, image_paths, *, reviewer, same_item_confirmed, scope, shared_with):
        _id(item_id)
        _string(reviewer)
        if same_item_confirmed is not True:
            raise PhotoEvidenceError("Explicit same-item grouping confirmation is required")
        shared_with = [] if shared_with is None else shared_with
        _scope(scope, shared_with)
        if type(image_paths) not in (list, tuple) or not 1 <= len(image_paths) <= MAX_PHOTOS:
            raise PhotoEvidenceError("Intake photo count limit")
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == item_id), None)
        if item is None:
            if len(state["items"]) >= MAX_ITEMS:
                raise PhotoEvidenceError("Item count limit")
            item = {"item_id": item_id, "scope": scope, "shared_with": copy.deepcopy(shared_with),
                    "quantity": None, "quantity_reviewer": None, "ownership": "unknown", "photos": [], "review": None, "history": []}
            state["items"].append(item)
        elif (item["scope"], item["shared_with"]) != (scope, shared_with):
            raise PhotoEvidenceError("Change sharing through explicit set_sharing review")
        seen = {p["sha256"]: x["item_id"] for x in state["items"] for p in x["photos"]}
        prior_photos = copy.deepcopy(item["photos"])
        staged = {}
        for path in image_paths:
            raw = _read(path, MAX_IMAGE)
            digest = hashlib.sha256(raw).hexdigest()
            media = _media(raw)
            if digest in seen and seen[digest] != item_id:
                raise PhotoEvidenceError("Photo belongs to another group; no duplicate inventory item")
            if digest in seen or digest in staged:
                continue
            staged[digest] = raw
            item["photos"].append({"sha256": digest, "bytes": len(raw), "media_type": media})
        if not staged:
            return copy.deepcopy(item)
        self._event(item, "intake", reviewer)
        item["history"][-1]["prior_photos"] = prior_photos
        item["review"] = None
        if "ocr_review" in item:
            item["ocr_review"] = None
        self._prepare_next(state)
        budget = self._layout_budget()
        absent = [digest for digest in staged if not (self.root / "images" / (digest + ".bin")).exists()]
        extra = sum(len(staged[digest]) for digest in absent)
        if budget["bytes"] + extra > MAX_TOTAL_IMAGES or budget["images"] + len(absent) > MAX_ITEMS * MAX_PHOTOS:
            raise PhotoEvidenceError("Stored image byte/count budget exceeded")
        for digest, raw in staged.items():
            target = self.root / "images" / (digest + ".bin")
            if target.exists():
                if _read(target, MAX_IMAGE) != raw:
                    raise PhotoEvidenceError("Existing image bytes differ")
            else:
                _atomic(target, raw)
        self._publish_locked(state)
        return self.get(item_id)


    def _capture_locked(self, item_id, state, *, provider_selection_sha256, ai_config_sha256):
        """Caller holds _writer; capture all original hashes and current reviews."""
        from .photo_ocr import make_capture
        item = next((row for row in state["items"] if row["item_id"] == _id(item_id)), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        return make_capture(
            app_id=APP_ID, project_id=self.project_id, root_binding=self.binding,
            revision=state["revision"], item_id=item_id,
            state_sha256=hashlib.sha256(_json_bytes(state)).hexdigest(),
            review_sha256=_review_sha256(item), photos=copy.deepcopy(item["photos"]),
            provider_selection_sha256=provider_selection_sha256,
            ai_config_sha256=ai_config_sha256)

    def capture_for_ocr(self, item_id):
        """Read-only bound capture; requires explicit policy/config but no native job."""
        from .photo_ocr_flow import capture
        return capture(self, item_id)

    def get(self, item_id):
        _id(item_id)
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == item_id), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        return copy.deepcopy(item)

    def review(self, item_id, *, reviewer, expected_subject, observations, confirm_identity=False):
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == _id(item_id)), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        _choice(expected_subject, SUBJECTS | {"assembly"})
        if type(confirm_identity) is not bool:
            raise PhotoEvidenceError("Invalid review request")
        _observations(observations, item["photos"])
        self._event(item, "review", reviewer)
        if "ocr_review" in item:
            item["ocr_review"] = None
        item["review"] = {"reviewer": reviewer, "expected_subject": expected_subject,
                          "confirm_identity": confirm_identity, "observations": copy.deepcopy(observations)}
        self._commit(state)
        return evaluate(self.get(item_id))

    def confirm_quantity(self, item_id, quantity, *, reviewer, ownership="unknown"):
        _positive(quantity, 10000)
        if type(ownership) is not str or ownership not in {"unknown", "owned", "borrowed"}:
            raise PhotoEvidenceError("Invalid explicit ownership")
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == _id(item_id)), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        self._event(item, "quantity", reviewer)
        if item.get("ocr_review") is not None:
            item["ocr_review"]["confirm_identity"] = False
        item["quantity"], item["quantity_reviewer"], item["ownership"] = quantity, reviewer, ownership
        self._commit(state)
        return self.get(item_id)

    def set_sharing(self, item_id, *, scope, shared_with, reviewer):
        _scope(scope, shared_with)
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == _id(item_id)), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        self._event(item, "sharing", reviewer)
        if item.get("ocr_review") is not None:
            item["ocr_review"]["confirm_identity"] = False
        item["scope"], item["shared_with"] = scope, copy.deepcopy(shared_with)
        self._commit(state)
        return self.get(item_id)


    def _evaluation(self, item):
        value = evaluate(item)
        if item.get("ocr_review") is not None:
            from .photo_ocr_flow import review_current
            if not review_current(self, item["ocr_review"]):
                value["status"] = "conflicting" if value["conflicts"] else "provisional"
                value["confidence"] = "unknown"
                value["recognition"] = ("synthetic-evidence-only" if item["ocr_review"]["test_only"]
                                        else "stale-local-ocr-review")
                value["follow_up"] = "Local OCR policy/configuration or qualification is unavailable or changed; explicitly recapture or clear OCR review."
        return value

    def inventory_items(self, *, project_id, include_shared=False):
        _id(project_id)
        if type(include_shared) is not bool:
            raise PhotoEvidenceError("Invalid sharing choice")
        state = self._load()
        items = []
        for item in state["items"]:
            own = project_id == self.project_id
            shared = (include_shared and item["scope"] == "equipment" and project_id in item["shared_with"])
            if not (own or shared):
                continue
            evaluation = self._evaluation(item)
            review = item["review"]
            subject = (item["ocr_review"]["expected_subject"] if item.get("ocr_review")
                       else review["expected_subject"] if review else "unknown")
            identity = evaluation["identities"].get(subject)
            equipment_id = "photo-" + APP_ID + "-" + hashlib.sha256(
                _json_bytes([APP_ID, self.project_id, self.binding, item["item_id"]])).hexdigest()
            items.append({"equipment_id": equipment_id,
                          "name": identity["name"] if identity else "Grouped part awaiting identification",
                          "manufacturer": "NVIDIA" if identity else None,
                          "model": identity["code"] if identity else None,
                          "category": "robotics_hardware", "quantity": item["quantity"],
                          "ownership_status": item["ownership"], "capabilities": [], "specs": {},
                          "verified": False, "source": "reviewed_local_photo_ledger",
                          "photo_status": evaluation["status"], "photo_project_id": self.project_id,
                          "photo_revision": str(state["revision"]), "photo_scope": item["scope"],
                          "notes": ("Synthetic OCR receipt fixture; recognition unqualified; no hardware/BOM validation."
                                    if item.get("ocr_review") and item["ocr_review"]["test_only"] else
                                    "Human-reviewed local OCR public-code evidence; qualification declared/unverified; no hardware/BOM validation."
                                    if item.get("ocr_review") else
                                    "Human photo review; recognition unavailable; no hardware/BOM validation.")})
        return items

    def result(self, item_id):
        state = self._load()
        item = next((x for x in state["items"] if x["item_id"] == _id(item_id)), None)
        if item is None:
            raise PhotoEvidenceError("Unknown grouped inventory item")
        evaluation = self._evaluation(item)
        value = {"project_id": self.project_id, "revision": str(state["revision"]), "item_id": item_id,
                "status": evaluation["status"], "quantity": item["quantity"], "ownership": item["ownership"], "scope": item["scope"],
                "shared_with": copy.deepcopy(item["shared_with"]), "photos": copy.deepcopy(item["photos"]),
                "identities": evaluation["identities"], "confidence": evaluation["confidence"],
                "unresolved_model_code_count": evaluation["unresolved_model_code_count"],
                "follow_up": evaluation["follow_up"], "recognition": evaluation["recognition"],
                "original_image_bytes_in_bundle": False, "image_verification": "unavailable",
                "local_image_verification": "sha256-and-byte-count-checked",
                "limits": ("Human-reviewed public codes only; original images, raw OCR and private paths are excluded from Aster bundles."
                           if item.get("ocr_review") else
                           "Byte integrity and manual transcription only; original images are excluded from Aster bundles.")}
        if item.get("ocr_review") is not None:
            row = item["ocr_review"]
            value["ocr_provenance"] = {
                "receipt_sha256": row["receipt_sha256"], "catalog_sha256": row["catalog_sha256"],
                "engine_sha256": row["engine_sha256"], "test_only": row["test_only"],
                "verification": "local-byte-integrity-only",
                "qualification": "synthetic-unqualified" if row["test_only"] else "declared-unverified",
            }
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--project", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    intake = commands.add_parser("intake")
    intake.add_argument("item")
    intake.add_argument("images", nargs="+")
    intake.add_argument("--reviewer", required=True)
    intake.add_argument("--same-item-confirmed", action="store_true")
    review = commands.add_parser("review")
    review.add_argument("item")
    review.add_argument("json_file", help="Strict JSON containing reviewer, expected_subject, observations, confirm_identity")
    quantity = commands.add_parser("quantity")
    quantity.add_argument("item")
    quantity.add_argument("quantity", type=int)
    quantity.add_argument("--reviewer", required=True)
    quantity.add_argument("--ownership", choices=("unknown", "owned", "borrowed"), default="unknown")
    result = commands.add_parser("result")
    result.add_argument("item")
    commands.add_parser("list")
    args = parser.parse_args()
    ledger = PhotoLedger(args.store, args.project)
    if args.command == "intake":
        value = ledger.intake(args.item, args.images, reviewer=args.reviewer, same_item_confirmed=args.same_item_confirmed)
    elif args.command == "review":
        value = _decode(_read(args.json_file, MAX_STATE))
        _keys(value, {"reviewer", "expected_subject", "observations", "confirm_identity"})
        value = ledger.review(args.item, **value)
    elif args.command == "quantity":
        value = ledger.confirm_quantity(args.item, args.quantity, reviewer=args.reviewer, ownership=args.ownership)
    elif args.command == "result":
        value = ledger.result(args.item)
    else:
        value = ledger.inventory_items(project_id=args.project)
    print(_json_bytes(value).decode("utf-8"), end="")


if __name__ == "__main__":
    main()
