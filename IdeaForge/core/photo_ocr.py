"""Optional local, bounded Tesseract perception. Disabled until explicitly qualified.

No decoding or OCR happens on import. Unknown OCR text stays in a private receipt.
This module does not write inventory, invoke providers, or infer board appearance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
import threading
import time
from decimal import Decimal, InvalidOperation

MAX_JSON = 65536
MAX_IMAGE = 1048576
MAX_PIXELS = 2000000
MAX_DERIVED = 8 * 1048576
MAX_TSV = 262144
MAX_WORDS = 128
MAX_FILES = 1010  # Guard reserves five code/input pins plus nine qualification receipts.
MAX_RUNTIME = 256 * 1048576 - 3 * MAX_JSON - 8192 - MAX_IMAGE - 9 * 8192
MAX_SCRATCH = 64 * 1048576
SHA = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
APPS = {"ideaforge", "humanoidresearcher"}
CAPTURE_FORMAT = "photo-ocr.capture.v1"
RECEIPT_FORMAT = "photo-ocr.candidate.v1"
CONFIG_FORMAT = "photo-ocr.selection.v1"
REQUIRED_TESTS = {
    "containment", "timeout", "overflow", "decode-negative", "pixel-positive",
    "pixel-negative", "pixel-ambiguous", "pixel-conflict", "project-isolation",
}
NVIDIA_ORIN = "https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/index.html"
NVIDIA_BRINGUP = ("https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/"
                 "HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html")
NVIDIA_NANO = "https://developer.nvidia.com/embedded/dlc/jetson_nano_developer_kit_user_guide"
# Exact complete public codes only. No full 699 mapping is qualified in this catalog.
CATALOG = {
    "P3767-0000": ("module", "Jetson Orin NX 16GB", 16, NVIDIA_ORIN, "35.3.1", "Devices Supported by This Document"),
    "P3767-0001": ("module", "Jetson Orin NX 8GB", 8, NVIDIA_ORIN, "35.3.1", "Devices Supported by This Document"),
    "P3767-0003": ("module", "Jetson Orin Nano 8GB", 8, NVIDIA_ORIN, "35.3.1", "Devices Supported by This Document"),
    "P3767-0004": ("module", "Jetson Orin Nano 4GB", 4, NVIDIA_ORIN, "35.3.1", "Devices Supported by This Document"),
    "P3767-0005": ("module", "Jetson Orin Nano 8GB with SD card slot", 8, NVIDIA_ORIN, "35.3.1", "Devices Supported by This Document"),
    "P3768-0000": ("carrier", "Jetson Orin Nano reference carrier", None, NVIDIA_BRINGUP, "35.3.1", "Porting the Linux Kernel Device Tree Files"),
    "P3448-0000": ("module", "Jetson Nano developer-kit module", None, NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "P3449-0000": ("carrier", "Jetson Nano reference carrier", None, NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "945-13450-0000-100": ("developer_kit", "Jetson Nano developer kit with B01 carrier", None, NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
    "945-13450-0000-000": ("developer_kit", "Jetson Nano developer kit with A02 carrier", None, NVIDIA_NANO, "DA_09402_004", "Introduction, printed page 1"),
}


class OcrError(ValueError):
    """Controlled refusal; messages never include private OCR text or input paths."""


class OcrUnavailable(OcrError):
    """No qualified local perception selection. There is no fallback."""


def _keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise OcrError("Missing or unknown object fields")


def _text(value, maximum=240, *, empty=False):
    if type(value) is not str or (not value and not empty):
        raise OcrError("Expected a bounded string")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise OcrError("Invalid Unicode") from exc
    if length > maximum or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise OcrError("String limit or control character")
    return value


def _hash(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise OcrError("Invalid SHA256")
    return value


def _id(value):
    if type(value) is not str or not ID.fullmatch(value):
        raise OcrError("Invalid portable identity")
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise OcrError("Integer bound")
    return value


def _choice(value, choices):
    if type(value) is not str or value not in choices:
        raise OcrError("Invalid enum")
    return value


def canonical_bytes(value):
    try:
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise OcrError("Invalid JSON") from exc
    if not 1 <= len(raw) <= MAX_JSON:
        raise OcrError("JSON byte bound")
    return raw


def decode_json(raw, max_bytes=MAX_JSON):
    if type(raw) is not bytes or not 1 <= len(raw) <= min(max_bytes, MAX_JSON):
        raise OcrError("JSON byte bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise OcrError("Duplicate JSON key")
            result[key] = value
        return result
    def bad(_):
        raise OcrError("Nonfinite JSON")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OcrError("Invalid strict JSON") from exc
    nodes = 0
    def visit(obj, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 6000:
            raise OcrError("JSON complexity bound")
        if type(obj) is dict:
            for key, child in obj.items():
                _text(key, 128)
                nodes += 1
                visit(child, depth + 1)
        elif type(obj) is list:
            if len(obj) > MAX_FILES:
                raise OcrError("JSON array bound")
            for child in obj:
                visit(child, depth + 1)
        elif type(obj) is str:
            _text(obj, 2048, empty=True)
        elif type(obj) is int:
            if obj.bit_length() > 128:
                raise OcrError("JSON integer bound")
        elif obj is not None and type(obj) is not bool:
            raise OcrError("Only integer JSON numbers are accepted")
    visit(value)
    return value


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


CATALOG_SHA256 = _digest(CATALOG)


def validate_capture(capture):
    _keys(capture, {"format", "app_id", "project_id", "root_binding", "revision",
                    "item_id", "state_sha256", "review_sha256", "provider_selection_sha256", "ai_config_sha256", "photos"})
    if capture["format"] != CAPTURE_FORMAT:
        raise OcrError("Unknown capture format")
    _choice(capture["app_id"], APPS)
    _id(capture["project_id"])
    _id(capture["item_id"])
    for key in ("root_binding", "state_sha256", "review_sha256", "provider_selection_sha256", "ai_config_sha256"):
        _hash(capture[key])
    _integer(capture["revision"], 1, 128)
    photos = capture["photos"]
    if type(photos) is not list or not 1 <= len(photos) <= 6:
        raise OcrError("Photo count bound")
    seen = set()
    for photo in photos:
        _keys(photo, {"sha256", "bytes", "media_type"})
        digest = _hash(photo["sha256"])
        if digest in seen:
            raise OcrError("Duplicate photo")
        seen.add(digest)
        _integer(photo["bytes"], 1, MAX_IMAGE)
        _choice(photo["media_type"], {"image/png", "image/jpeg", "image/webp"})
    canonical_bytes(capture)
    return copy.deepcopy(capture)


def make_capture(app_id, project_id, root_binding, revision, item_id, photos,
                 *, state_sha256, review_sha256, provider_selection_sha256, ai_config_sha256):
    return validate_capture({"format": CAPTURE_FORMAT, "app_id": app_id,
        "project_id": project_id, "root_binding": root_binding, "revision": revision,
        "item_id": item_id, "state_sha256": state_sha256,
        "review_sha256": review_sha256, "provider_selection_sha256": provider_selection_sha256,
        "ai_config_sha256": ai_config_sha256, "photos": copy.deepcopy(photos)})


def _portable_path(value):
    _text(value, 240)
    if "\\" in value or ":" in value or value.startswith("/") or len(value.split("/")) > 8:
        raise OcrError("Invalid runtime relative path")
    for component in value.split("/"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", component) or component.endswith("."):
            raise OcrError("Invalid runtime path component")
        stem = component.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[0-9]", stem):
            raise OcrError("Reserved path")
    return value


def _local(path):
    if type(path) not in (str, Path) and not isinstance(path, Path):
        raise OcrError("Expected local path")
    p = Path(path)
    if not p.is_absolute() or str(p).startswith(("\\\\", "//")):
        raise OcrError("Absolute local path required")
    for part in (p, *p.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OcrError("Reparse or symlink path")
    return p


def _read(path, maximum):
    path = _local(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= maximum:
            raise OcrError("File type, link or byte bound")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        current = path.stat()
        sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if len(raw) != before.st_size or sig(before) != sig(after) or sig(after) != sig(current):
            raise OcrError("File changed during read")
        _local(path)
        return raw
    finally:
        os.close(fd)


def validate_config(config):
    _keys(config, {"format", "enabled", "runtime_root", "python", "engine", "model",
                   "pillow_root", "files", "code_sha256", "catalog_sha256",
                   "engine_version", "pillow_version", "os_version", "qualification"})
    if config["format"] != CONFIG_FORMAT or type(config["enabled"]) is not bool:
        raise OcrError("Invalid local OCR selection")
    _text(config["runtime_root"], 2048)
    for name in ("python", "engine", "model", "pillow_root"):
        _portable_path(config[name])
    if not config["model"].endswith("/eng.traineddata"):
        raise OcrError("Only the pinned English model is supported")
    if config["engine_version"] != "5.5.3":
        raise OcrError("Unsupported engine version")
    if not re.fullmatch(r"(10|11|12)\.[0-9]+\.[0-9]+", _text(config["pillow_version"], 64)):
        raise OcrError("Unsupported Pillow version")
    _text(config["os_version"], 128)
    if config["catalog_sha256"] != CATALOG_SHA256:
        raise OcrError("Catalog selection mismatch")
    _keys(config["code_sha256"], {"photo_ocr.py", "ocr_worker.py", "ocr_guard.py"})
    for value in config["code_sha256"].values():
        _hash(value)
    files = config["files"]
    if type(files) is not list or not 1 <= len(files) <= MAX_FILES:
        raise OcrError("Runtime closure file count")
    names, total = set(), 0
    for entry in files:
        _keys(entry, {"path", "sha256", "bytes"})
        path = _portable_path(entry["path"])
        if path.casefold() in names:
            raise OcrError("Case-colliding runtime paths")
        names.add(path.casefold())
        _hash(entry["sha256"])
        total += _integer(entry["bytes"], 1, 128 * 1048576)
    if total > MAX_RUNTIME:
        raise OcrError("Runtime closure byte bound")
    for role in ("python", "engine", "model"):
        if config[role] not in {f["path"] for f in files}:
            raise OcrError("Runtime role is outside closure")
    prefix = config["pillow_root"] + "/PIL/"
    if not any(f["path"].startswith(prefix) for f in files):
        raise OcrError("Pillow is outside closure")
    qualification = config["qualification"]
    if qualification is not None:
        _keys(qualification, {"format", "runtime_sha256", "code_sha256", "catalog_sha256",
                              "engine_version", "pillow_version", "os_version", "receipt_root", "tests"})
        if qualification["format"] != "photo-ocr.qualification.v1":
            raise OcrError("Unknown qualification format")
        expected = {
            "runtime_sha256": _digest(files), "code_sha256": config["code_sha256"],
            "catalog_sha256": config["catalog_sha256"], "engine_version": config["engine_version"],
            "pillow_version": config["pillow_version"], "os_version": config["os_version"],
        }
        if any(qualification[k] != v for k, v in expected.items()):
            raise OcrError("Qualification selection binding mismatch")
        _text(qualification["receipt_root"], 2048)
        tests = qualification["tests"]
        if type(tests) is not list or len(tests) != len(REQUIRED_TESTS):
            raise OcrError("Qualification test set mismatch")
        test_ids, receipt_paths = set(), set()
        for row in tests:
            _keys(row, {"id", "status", "receipt_path", "receipt_sha256", "receipt_bytes"})
            if _text(row["id"], 64) not in REQUIRED_TESTS or row["id"] in test_ids:
                raise OcrError("Qualification test identity mismatch")
            test_ids.add(row["id"])
            _choice(row["status"], {"passed", "failed", "unrun"})
            _hash(row["receipt_sha256"])
            _integer(row["receipt_bytes"], 1, 8192)
            path = _portable_path(row["receipt_path"])
            if path.casefold() in receipt_paths:
                raise OcrError("Case-colliding qualification receipt paths")
            receipt_paths.add(path.casefold())
    canonical_bytes(config)
    return copy.deepcopy(config)


def load_config(raw):
    value = validate_config(decode_json(raw))
    return value


def _checkpoint(deadline, cancel):
    if cancel is not None and cancel.is_set():
        raise OcrError("Local OCR was cancelled")
    if deadline is not None and time.monotonic() >= deadline:
        raise OcrError("Perception group deadline")


def _hash_file(path, maximum, *, deadline=None, cancel=None):
    """Streaming pinned file read; bounded chunks with cancellation checkpoints."""
    path = _local(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= maximum:
            raise OcrError("File type, link or byte bound")
        digest, count = hashlib.sha256(), 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while True:
                _checkpoint(deadline, cancel)
                block = stream.read(min(65536, maximum + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > maximum:
                    raise OcrError("Pinned file byte bound")
                digest.update(block)
        _checkpoint(deadline, cancel)
        after, current = os.fstat(fd), path.stat()
        sig = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
        if count != before.st_size or sig(before) != sig(after) or sig(after) != sig(current):
            raise OcrError("Pinned file changed during read")
        _local(path)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _runtime_files(config, *, deadline=None, cancel=None):
    root = _local(config["runtime_root"])
    if not root.is_dir():
        raise OcrUnavailable("Qualified local runtime is missing")
    wanted = {entry["path"]: entry for entry in config["files"]}
    actual, directories, entries_seen, pending = set(), 0, 0, [root]
    # scandir iterator bounds enumeration itself; no unbounded os.walk list allocation.
    while pending:
        _checkpoint(deadline, cancel)
        directory = pending.pop()
        directories += 1
        if directories > MAX_FILES * 2:
            raise OcrError("Runtime directory count bound")
        with os.scandir(_local(directory)) as entries:
            for entry in entries:
                _checkpoint(deadline, cancel)
                entries_seen += 1
                if entries_seen > MAX_FILES * 3:
                    raise OcrError("Runtime entry count bound")
                path = _local(Path(entry.path))
                relative = path.relative_to(root).as_posix()
                _portable_path(relative)
                if entry.is_dir(follow_symlinks=False):
                    if len(pending) >= MAX_FILES * 2:
                        raise OcrError("Runtime directory count bound")
                    pending.append(path)
                    continue
                if len(actual) >= MAX_FILES or relative not in wanted:
                    raise OcrError("Unlisted runtime file")
                info = path.lstat()
                entry_pin = wanted[relative]
                if info.st_size != entry_pin["bytes"]:
                    raise OcrError("Runtime pin byte mismatch")
                if _hash_file(path, entry_pin["bytes"], deadline=deadline, cancel=cancel) != entry_pin["sha256"]:
                    raise OcrError("Runtime pin mismatch")
                actual.add(relative)
    if actual != set(wanted):
        raise OcrUnavailable("Qualified local runtime closure is incomplete")
    return {str(root / entry["path"]): entry["sha256"] for entry in config["files"]}

def _qualification_files(config, *, deadline=None, cancel=None):
    """Read real hashed local receipt bytes; retain operator trust explicitly.

    A receipt cannot authenticate its claimed observation or test result. Qualified
    use requires a reviewer to inspect the actual separately performed test run.
    """
    qualification = config["qualification"]
    if qualification is None:
        raise OcrUnavailable("No reviewed local qualification evidence")
    root = _local(qualification["receipt_root"])
    files = {row["path"] for row in config["files"]}
    expected = {key: qualification[key] for key in (
        "runtime_sha256", "code_sha256", "catalog_sha256", "engine_version",
        "pillow_version", "os_version")}
    pins, observed = {}, set()
    for descriptor in qualification["tests"]:
        _checkpoint(deadline, cancel)
        if descriptor["status"] != "passed":
            raise OcrUnavailable("Local OCR qualification is incomplete")
        path = _local(root / descriptor["receipt_path"])
        raw = _read(path, descriptor["receipt_bytes"])
        _checkpoint(deadline, cancel)
        if len(raw) != descriptor["receipt_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["receipt_sha256"]:
            raise OcrError("Qualification receipt byte hash mismatch")
        record = decode_json(raw, 8192)
        _keys(record, {"format", "id", "status", "runtime_sha256", "code_sha256",
                       "catalog_sha256", "engine_version", "pillow_version", "os_version",
                       "elapsed_ms", "peak_job_memory_bytes", "owned_job_empty",
                       "loaded_runtime_paths", "test_only"})
        if (record["format"], record["id"], record["status"]) != (
                "photo-ocr.qualification-test.v1", descriptor["id"], "passed"):
            raise OcrError("Qualification receipt identity mismatch")
        if any(canonical_bytes(record[key]) != canonical_bytes(value) for key, value in expected.items()):
            raise OcrError("Qualification receipt selection mismatch")
        _integer(record["elapsed_ms"], 0, 30000)
        _integer(record["peak_job_memory_bytes"], 0, 512 * 1048576)
        if record["owned_job_empty"] is not True or record["test_only"] is not False:
            raise OcrUnavailable("Qualification requires actual owned cleanup evidence")
        loaded = record["loaded_runtime_paths"]
        if type(loaded) is not list or len(loaded) > MAX_FILES:
            raise OcrError("Qualification loaded-file count")
        local_seen = set()
        for relative in loaded:
            _portable_path(relative)
            if relative not in files or relative.casefold() in local_seen:
                raise OcrError("Qualification loaded-file binding")
            local_seen.add(relative.casefold())
            observed.add(relative)
        pins[str(path)] = descriptor["receipt_sha256"]
    required = {config["python"], config["engine"], config["model"]}
    decoder_prefix = config["pillow_root"] + "/PIL/"
    has_decoder = any(path.startswith(decoder_prefix) and Path(path).name.startswith("_imaging")
                      and path.endswith(".pyd") for path in observed)
    if not required <= observed or not has_decoder:
        raise OcrUnavailable("Actual Python engine model and Pillow decoder closure observation is required")
    return pins


def parse_tsv(raw, width, height):
    """Strict Tesseract TSV parser. Word confidence is a diagnostic, not probability."""
    _integer(width, 1, MAX_PIXELS)
    _integer(height, 1, MAX_PIXELS)
    if width * height > MAX_PIXELS or type(raw) is not bytes or len(raw) > MAX_TSV:
        raise OcrError("TSV/pixel byte bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise OcrError("TSV encoding") from exc
    lines = text.splitlines()
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    if not lines or lines[0] != header or len(lines) > 1025:
        raise OcrError("TSV header or row bound")
    words, identities = [], set()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 12:
            raise OcrError("Malformed TSV row")
        try:
            nums = [int(x) for x in fields[:10]]
            if any(not re.fullmatch(r"[0-9]{1,8}", x) for x in fields[:10]):
                raise ValueError()
            level, page, block, par, row, word, left, top, boxw, boxh = nums
            if not 1 <= level <= 5 or page != 1 or min(left, top, boxw, boxh) < 0:
                raise ValueError()
            if left + boxw > width or top + boxh > height:
                raise ValueError()
            confidence = Decimal(fields[10])
            if not confidence.is_finite():
                raise ValueError()
        except (ValueError, InvalidOperation) as exc:
            raise OcrError("Malformed TSV numeric field") from exc
        if level != 5:
            if fields[11] or confidence != -1:
                raise OcrError("Unexpected TSV layout text")
            continue
        if not all(1 <= x <= 10000 for x in (block, par, row, word)) or boxw == 0 or boxh == 0:
            raise OcrError("Invalid TSV word identity/box")
        if not 0 <= confidence <= 100 or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,6})?", fields[10]):
            raise OcrError("Invalid TSV word confidence")
        token = _text(fields[11], 96)
        identity = (block, par, row, word)
        if identity in identities or len(words) >= MAX_WORDS:
            raise OcrError("Duplicate TSV word or word bound")
        identities.add(identity)
        words.append({"text": token, "bbox": [left, top, boxw, boxh],
                      "confidence_milli": int(confidence * 1000),
                      "line": [block, par, row]})
    return words


def _words(words, width, height):
    if type(words) is not list or len(words) > MAX_WORDS:
        raise OcrError("Word bound")
    for row in words:
        _keys(row, {"text", "bbox", "confidence_milli", "line"})
        _text(row["text"], 96)
        _integer(row["confidence_milli"], 0, 100000)
        if type(row["bbox"]) is not list or len(row["bbox"]) != 4:
            raise OcrError("Word box shape")
        x, y, w, h = row["bbox"]
        _integer(x, 0, width)
        _integer(y, 0, height)
        _integer(w, 1, width)
        _integer(h, 1, height)
        if x + w > width or y + h > height:
            raise OcrError("Word box outside image")
        if type(row["line"]) is not list or len(row["line"]) != 3:
            raise OcrError("Word line shape")
        for value in row["line"]:
            _integer(value, 1, 10000)


def _matching(images):
    matches, role_codes, unresolved = [], {}, 0
    for image in images:
        for index, word in enumerate(image["words"]):
            token = word["text"]
            if token in CATALOG:
                subject, name, memory, url, revision, locator = CATALOG[token]
                match_id = hashlib.sha256(
                    (image["photo_sha256"] + ":" + str(index) + ":" + token).encode("ascii")).hexdigest()
                matches.append({"id": match_id, "photo_sha256": image["photo_sha256"],
                    "word_index": index, "code": token, "subject": subject, "name": name,
                    "memory_gb": memory, "source_url": url, "source_revision": revision,
                    "source_locator": locator, "hardware_revision": "unknown"})
                role_codes.setdefault(subject, set()).add(token)
                if word["confidence_milli"] < 85000:
                    unresolved += 1  # Diagnostic threshold, not an identity probability.
            elif (re.match(r"[Pp][0-9OIil]", token) or token.startswith(("699-", "945-"))):
                # Partial codes and OCR character confusions are unresolved, never repaired.
                unresolved += 1
    conflicts = ["Different exact codes identify the same component kind"
                 for codes in role_codes.values() if len(codes) > 1]
    conflicts = sorted(set(conflicts))
    status = "conflicting" if conflicts else "unresolved" if unresolved or not matches else "candidate"
    return {"status": status, "matches": matches, "unresolved_count": unresolved, "conflicts": conflicts}


def _validate_images(images, capture):
    if type(images) is not list or len(images) != len(capture["photos"]):
        raise OcrError("Receipt must cover every captured view")
    word_count = 0
    for image, photo in zip(images, capture["photos"]):
        _keys(image, {"photo_sha256", "bytes", "derived_sha256", "width", "height",
                     "transform", "tsv_sha256", "words", "elapsed_ms", "peak_job_memory_bytes"})
        _integer(image["bytes"], 1, MAX_IMAGE)
        if (image["photo_sha256"], image["bytes"]) != (photo["sha256"], photo["bytes"]):
            raise OcrError("Receipt input binding mismatch")
        for key in ("photo_sha256", "derived_sha256", "tsv_sha256"):
            _hash(image[key])
        width = _integer(image["width"], 1, MAX_PIXELS)
        height = _integer(image["height"], 1, MAX_PIXELS)
        if width * height > MAX_PIXELS or image["transform"] != "identity-no-exif":
            raise OcrError("Derived geometry mismatch")
        _words(image["words"], width, height)
        word_count += len(image["words"])
        if word_count > MAX_WORDS:
            raise OcrError("Group word bound")
        _integer(image["elapsed_ms"], 0, 5000)
        _integer(image["peak_job_memory_bytes"], 0, 512 * 1048576)


def _engine(engine):
    _keys(engine, {"name", "version", "runtime_sha256", "model_sha256", "code_sha256"})
    if engine["name"] != "tesseract" or engine["version"] != "5.5.3":
        raise OcrError("Receipt engine mismatch")
    for key in ("runtime_sha256", "model_sha256", "code_sha256"):
        _hash(engine[key])


def _receipt(capture, selection_sha256, engine, images, *, test_only=False):
    capture = validate_capture(capture)
    _hash(selection_sha256)
    _engine(engine)
    _validate_images(images, capture)
    matched = _matching(images)
    receipt = {"format": RECEIPT_FORMAT, "capture": capture,
               "selection_sha256": selection_sha256, "catalog_sha256": CATALOG_SHA256,
               "engine": copy.deepcopy(engine), "images": copy.deepcopy(images),
               **matched, "metrics": {"elapsed_ms": sum(x["elapsed_ms"] for x in images),
                   "peak_job_memory_bytes": max(x["peak_job_memory_bytes"] for x in images)},
               "test_only": test_only}
    return validate_receipt(receipt, expected_capture=capture,
                            expected_selection_sha256=selection_sha256)


def validate_receipt(receipt, expected_capture, expected_selection_sha256=None, expected_config=None):
    _keys(receipt, {"format", "capture", "selection_sha256", "catalog_sha256", "engine",
                    "images", "status", "matches", "unresolved_count", "conflicts", "metrics", "test_only"})
    if receipt["format"] != RECEIPT_FORMAT or type(receipt["test_only"]) is not bool:
        raise OcrError("Unknown candidate receipt")
    capture = validate_capture(receipt["capture"])
    if capture != validate_capture(expected_capture):
        raise OcrError("Stale or cross-project capture")
    _hash(receipt["selection_sha256"])
    if expected_selection_sha256 is not None and receipt["selection_sha256"] != _hash(expected_selection_sha256):
        raise OcrError("Stale OCR selection")
    if receipt["catalog_sha256"] != CATALOG_SHA256:
        raise OcrError("Stale catalog")
    _engine(receipt["engine"])
    if expected_config is not None and receipt["engine"] != engine_binding(expected_config):
        raise OcrError("Receipt engine does not match current selection")
    _validate_images(receipt["images"], capture)
    matched = _matching(receipt["images"])
    _choice(receipt["status"], {"candidate", "unresolved", "conflicting"})
    _integer(receipt["unresolved_count"], 0, MAX_WORDS)
    for key, value in matched.items():
        if canonical_bytes(receipt[key]) != canonical_bytes(value):
            raise OcrError("Candidate match summary mismatch")
    _keys(receipt["metrics"], {"elapsed_ms", "peak_job_memory_bytes"})
    metrics = {"elapsed_ms": sum(x["elapsed_ms"] for x in receipt["images"]),
               "peak_job_memory_bytes": max(x["peak_job_memory_bytes"] for x in receipt["images"])}
    _integer(receipt["metrics"]["elapsed_ms"], 0, 35000)
    _integer(receipt["metrics"]["peak_job_memory_bytes"], 0, 512 * 1048576)
    if receipt["metrics"] != metrics or metrics["elapsed_ms"] > 35000:
        raise OcrError("Metric binding mismatch")
    canonical_bytes(receipt)
    return copy.deepcopy(receipt)


def receipt_bytes(receipt):
    validate_receipt(receipt, receipt["capture"], receipt["selection_sha256"])
    return canonical_bytes(receipt)


def receipt_sha256(receipt):
    return hashlib.sha256(receipt_bytes(receipt)).hexdigest()


def candidates(receipt):
    checked = validate_receipt(receipt, receipt["capture"], receipt["selection_sha256"])
    return {name: copy.deepcopy(checked[name])
            for name in ("status", "matches", "unresolved_count", "conflicts")}


def _write_new(path, raw, maximum):
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise OcrError("Private scratch write bound")
    path = _local(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _run_ocr_locked(config, capture, *, store_root, selection_sha256, selection_bytes, cancel=None):
    """One explicit qualified local run, serial views; never adopts inventory.

    Qualification records are locally reviewed claims, not signed certifications.
    The app must approve the exact selection bytes and retain actual test evidence.
    """
    if cancel is not None and not isinstance(cancel, threading.Event):
        raise OcrError("Cancellation must use a threading.Event")
    _checkpoint(None, cancel)
    config, capture = validate_config(config), validate_capture(capture)
    if load_config(selection_bytes) != config or hashlib.sha256(selection_bytes).hexdigest() != _hash(selection_sha256):
        raise OcrError("Selection byte hash mismatch")
    if not config["enabled"] or config["qualification"] is None:
        raise OcrUnavailable("Local OCR is disabled or has no reviewed runtime qualification")
    if any(row["status"] != "passed" for row in config["qualification"]["tests"]):
        raise OcrUnavailable("Local OCR qualification is incomplete")
    if os.name != "nt" or platform.version() != config["os_version"]:
        raise OcrUnavailable("Qualified Windows environment is unavailable")
    root = _local(store_root)
    binding = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    if binding != capture["root_binding"]:
        raise OcrError("Store binding mismatch")
    start = time.monotonic()
    deadline = start + 35
    from .ocr_guard import run_guarded, GuardError
    pins = _qualification_files(config, deadline=deadline, cancel=cancel)
    pins.update(_runtime_files(config, deadline=deadline, cancel=cancel))
    directory = Path(__file__).absolute().parent
    for name, digest in config["code_sha256"].items():
        path = _local(directory / name)
        if _hash_file(path, MAX_JSON, deadline=deadline, cancel=cancel) != digest:
            raise OcrError("Adapter code pin mismatch")
        pins[str(path)] = digest
    runtime_root = _local(config["runtime_root"])
    python = runtime_root / config["python"]
    engine_path = runtime_root / config["engine"]
    model_path = runtime_root / config["model"]
    pillow_root = runtime_root / config["pillow_root"]
    model_entry = next(x for x in config["files"] if x["path"] == config["model"])
    engine = {"name": "tesseract", "version": "5.5.3",
              "runtime_sha256": _digest(config["files"]), "model_sha256": model_entry["sha256"],
              "code_sha256": _digest(config["code_sha256"])}
    system_root = _local(os.environ.get("SystemRoot", ""))
    images = []
    scratch_parent = _local(root / "ocr_scratch")
    scratch_parent.mkdir(exist_ok=True)
    if any(scratch_parent.iterdir()):
        raise OcrError("Private scratch requires explicit recovery before another run")
    # Only a single owned image directory exists at once: known writes < 10 MiB.
    for index, photo in enumerate(capture["photos"]):
        if cancel is not None and cancel.is_set():
            raise OcrError("Local OCR was cancelled")
        if time.monotonic() - start >= 35:
            raise OcrError("Group timeout")
        original = _read(root / "images" / (photo["sha256"] + ".bin"), MAX_IMAGE)
        if len(original) != photo["bytes"] or hashlib.sha256(original).hexdigest() != photo["sha256"]:
            raise OcrError("Original photo changed")
        scratch = Path(tempfile.mkdtemp(prefix="owned-", dir=scratch_parent))
        cleaned = False
        try:
            input_path, request_path = scratch / "input.bin", scratch / "request.json"
            _write_new(input_path, original, MAX_IMAGE)
            request = {"format": "photo-ocr.worker-request.v1",
                       "input_sha256": photo["sha256"], "input_bytes": photo["bytes"],
                       "media_type": photo["media_type"], "engine": str(engine_path),
                       "model": str(model_path), "pillow_root": str(pillow_root),
                       "pillow_version": config["pillow_version"],
                       "engine_sha256": next(x["sha256"] for x in config["files"] if x["path"] == config["engine"]),
                       "model_sha256": model_entry["sha256"]}
            request_raw = canonical_bytes(request)
            _write_new(request_path, request_raw, 8192)
            active_pins = dict(pins)
            active_pins[str(request_path)] = hashlib.sha256(request_raw).hexdigest()
            active_pins[str(input_path)] = photo["sha256"]
            image_environment = _worker_environment(system_root, scratch)
            result = run_guarded(python, ["-I", "-S", "-B", str(directory / "ocr_worker.py"), str(request_path)],
                cwd=scratch, environment=image_environment, timeout_seconds=min(5, 35 - (time.monotonic() - start)),
                stdout_limit=MAX_JSON, stderr_limit=16384, cancel=cancel, expected_sha256=active_pins)
            if result.exit_code != 0:
                raise OcrError("Perception worker refused the image")
            output = decode_json(result.stdout)
            _keys(output, {"format", "input_sha256", "input_bytes", "derived_sha256",
                          "width", "height", "transform", "tsv_sha256", "words"})
            _integer(output["input_bytes"], 1, MAX_IMAGE)
            if (output["format"], output["input_sha256"], output["input_bytes"]) != (
                    "photo-ocr.worker-result.v1", photo["sha256"], photo["bytes"]):
                raise OcrError("Worker input binding mismatch")
            image = {"photo_sha256": photo["sha256"], "bytes": photo["bytes"],
                     **{k: output[k] for k in ("derived_sha256", "width", "height", "transform", "tsv_sha256", "words")},
                     "elapsed_ms": result.elapsed_ms, "peak_job_memory_bytes": result.peak_job_memory_bytes}
            _validate_images([image], {**capture, "photos": [photo]})
            images.append(image)
            _runtime_files(config, deadline=deadline, cancel=cancel)
            # Guard success means owned Job empty; only these owned files are removed.
            for name, limit in (("input.bin", MAX_IMAGE), ("request.json", 8192), ("derived.png", MAX_DERIVED)):
                path = _local(scratch / name)
                if path.exists():
                    _read(path, limit)
            actual = {p.name for p in scratch.iterdir()}
            if actual - {"input.bin", "request.json", "derived.png"}:
                raise OcrError("Unexpected private scratch output")
            shutil.rmtree(scratch)
            cleaned = True
        except GuardError as exc:
            # Guard failures preserve scratch; never clean while owned process state is uncertain.
            raise OcrError("Native containment, timeout or output guard refused the run") from exc
        finally:
            if not cleaned:
                # Private failed evidence is deliberately retained for explicit local recovery.
                pass
    if time.monotonic() - start > 35:
        raise OcrError("Group timeout")
    return _receipt(capture, selection_sha256, engine, images, test_only=False)


def run_ocr(config, capture, *, store_root, selection_sha256, selection_bytes, cancel=None):
    """Explicit admission; no lock, import, file scan, decode or launch if unavailable."""
    if cancel is not None and not isinstance(cancel, threading.Event):
        raise OcrError("Cancellation must use a threading.Event")
    _checkpoint(None, cancel)
    config, capture = validate_config(config), validate_capture(capture)
    if load_config(selection_bytes) != config or hashlib.sha256(selection_bytes).hexdigest() != _hash(selection_sha256):
        raise OcrError("Selection byte hash mismatch")
    if not config["enabled"] or config["qualification"] is None:
        raise OcrUnavailable("Local OCR is disabled or has no reviewed runtime qualification")
    if any(row["status"] != "passed" for row in config["qualification"]["tests"]):
        raise OcrUnavailable("Local OCR qualification is incomplete")
    if os.name != "nt" or platform.version() != config["os_version"]:
        raise OcrUnavailable("Qualified Windows environment is unavailable")
    root = _local(store_root)
    if hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest() != capture["root_binding"]:
        raise OcrError("Store binding mismatch")
    lock = _local(root / "ocr-run-lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise OcrError("Perception lock exists; explicit local recovery required") from exc
    completed = False
    try:
        receipt = _run_ocr_locked(config, capture, store_root=root,
                                  selection_sha256=selection_sha256, selection_bytes=selection_bytes, cancel=cancel)
        completed = True
        return receipt
    finally:
        # Failure preserves the lock/scratch for review; no automatic retry or stale-lock removal.
        if completed:
            lock.rmdir()


def engine_binding(config):
    """Pure binding for review/restart; never probes an installed runtime."""
    config = validate_config(config)
    model = next(row for row in config["files"] if row["path"] == config["model"])
    return {"name": "tesseract", "version": "5.5.3",
            "runtime_sha256": _digest(config["files"]), "model_sha256": model["sha256"],
            "code_sha256": _digest(config["code_sha256"])}


def _worker_environment(system_root, scratch):
    """Exact fixed production environment; no ambient Python/provider variables."""
    return {"SystemRoot": str(system_root), "WINDIR": str(system_root),
            "PATH": str(Path(system_root) / "System32"),
            "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1",
            "TMP": str(scratch), "TEMP": str(scratch)}
