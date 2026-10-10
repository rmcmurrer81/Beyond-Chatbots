"""Local-only Aster result-bundle writer; never sends, executes or adopts data."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

FORMAT = "aster.research-bundle.v1"
RECEIPT_FORMAT = "aster.test-receipt.v1"
MAX_FILE = 262144
MAX_TOTAL = 1048576
SCHEMAS = {
    "humanoidresearcher": {
        "humanoidresearcher.assembly-compatibility.v1",
        "humanoidresearcher.reviewed-photo-inventory.v1",
    },
    "ideaforge": {
        "ideaforge.reviewed-parameter-link.v1",
        "ideaforge.reviewed-photo-inventory.v1",
    },
    "bluebook": {"bluebook.reviewed-case-association.v1"},
}
PORTABLE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
PORTABLE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)", re.I)
MEDIA = {"application/json", "text/plain"}


class BundleError(ValueError):
    pass


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise BundleError(f"{label}: missing or unknown fields")
    return value


def _text(value, maximum, label, *, multiline=False):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BundleError(f"{label}: nonempty UTF-8 text required")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise BundleError(f"{label}: invalid UTF-8 text") from exc
    if length > maximum or any((ord(c) < 32 and not (multiline and c in "\r\n\t"))
                               or 0x7F <= ord(c) <= 0x9F for c in value):
        raise BundleError(f"{label}: text bound/control-character violation")
    return value


def _id(value, label):
    if not isinstance(value, str) or PORTABLE_ID.fullmatch(value) is None:
        raise BundleError(f"{label}: portable identifier required")
    return value


def _path(value):
    _text(value, 240, "path")
    parts = value.split("/")
    if len(parts) > 8 or any(PORTABLE_PART.fullmatch(p) is None or p.endswith(".")
           or p in {".", ".."} or DEVICE.match(p) for p in parts):
        raise BundleError("path: only portable relative POSIX components supported")
    return parts


def _digest(value):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise BundleError("lowercase SHA-256 required")
    return value


def _bytes(value):
    if type(value) is not int or not 1 <= value <= MAX_FILE:
        raise BundleError("file size must be 1..262144 bytes")
    return value


def _array(value, maximum, label):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise BundleError(f"{label}: nonempty bounded list required")
    return value


def _bounded(value):
    stack = [(value, 0)]
    nodes = text_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 16 or nodes + len(stack) > 10000:
            raise BundleError("JSON nesting/node limit exceeded")
        if isinstance(item, dict):
            nodes += len(item)  # Object keys count as JSON nodes, as do values.
            if nodes + len(stack) + len(item) > 10000:
                raise BundleError("JSON node limit exceeded")
            for key in item:
                if not isinstance(key, str):
                    raise BundleError("JSON object keys must be text")
                text_bytes += _text_allow_empty(key)
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if nodes + len(stack) + len(item) > 10000:
                raise BundleError("JSON node limit exceeded")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            text_bytes += _text_allow_empty(item)
        elif type(item) is int:
            if item.bit_length() > 128:
                raise BundleError("JSON integer size unsupported")
        elif type(item) is float:
            if not math.isfinite(item):
                raise BundleError("nonfinite JSON value")
        elif item is not None and type(item) is not bool:
            raise BundleError("unsupported JSON type")
        if text_bytes > MAX_FILE:
            raise BundleError("JSON text budget exceeds 256 KiB")
    return value


def _text_allow_empty(value):
    if len(value) > 16384:
        raise BundleError("JSON string exceeds 16 KiB")
    try:
        if len(value.encode("utf-8")) > 16384:
            raise BundleError("JSON string exceeds 16 KiB")
        if any((ord(c) < 32 and c not in "\r\n\t") or 0x7F <= ord(c) <= 0x9F
               for c in value):
            raise BundleError("JSON string contains unsupported control characters")
    except UnicodeError as exc:
        raise BundleError("invalid UTF-8 JSON string") from exc
    return len(value.encode("utf-8"))


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BundleError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_constant(_):
    raise BundleError("nonfinite JSON constant")


def _json(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=_reject_constant)
        return _bounded(value)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise BundleError("invalid bounded UTF-8 JSON") from exc


def _encode(value):
    _bounded(value)
    try:
        raw = (json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, indent=2) + "\n").encode("utf-8")
    except (UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        raise BundleError("cannot encode bounded UTF-8 JSON") from exc
    if not 1 <= len(raw) <= MAX_FILE:
        raise BundleError("encoded JSON exceeds 256 KiB")
    return raw


def _reparse(info):
    return bool(getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _root(path):
    raw = str(path)
    if raw.startswith(("\\\\", "//")):
        raise BundleError("network project roots are unsupported")
    root = Path(path).absolute()
    for parent in (root, *root.parents):
        if parent.is_symlink() or _reparse(parent.lstat()):
            raise BundleError("symlink project roots/ancestors are unsupported")
    if not root.is_dir():
        raise BundleError("project root must be an existing directory")
    return root


def _checked_file(root, relative):
    root = _root(root)
    parts = _path(relative)
    path = root
    for index, part in enumerate(parts):
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or _reparse(info):
            raise BundleError("symlink paths are unsupported")
        if index != len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise BundleError("input parent is not a directory")
        if index == len(parts) - 1:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BundleError("inputs must be regular files with one hard link")
    return path, info


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)


def _read_input(root, entry):
    _keys(entry, {"id", "path", "sha256", "bytes", "media_type"}, "input")
    _id(entry["id"], "input.id")
    _digest(entry["sha256"])
    _bytes(entry["bytes"])
    if not isinstance(entry["media_type"], str) or entry["media_type"] not in MEDIA:
        raise BundleError("only JSON/text inputs supported; images are excluded")
    root_identity = _directory_id(_root(root).lstat())
    path, initial = _checked_file(root, entry["path"])
    if initial.st_size != entry["bytes"]:
        raise BundleError("input byte count mismatch")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if _signature(opened) != _signature(initial):
            raise BundleError("input changed before read")
        raw = handle.read(MAX_FILE + 1)
        after = os.fstat(handle.fileno())
    _, current = _checked_file(root, entry["path"])
    if _directory_id(_root(root).lstat()) != root_identity:
        raise BundleError("project root changed during input read")
    if (_signature(after) != _signature(initial)
            or _signature(current) != _signature(initial)):
        raise BundleError("input changed during read")
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise BundleError("input hash/byte count mismatch")
    if entry["media_type"] == "application/json":
        _json(raw)
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise BundleError("text input is not UTF-8") from exc
        if any((ord(c) < 32 and c not in "\r\n\t") or 0x7F <= ord(c) <= 0x9F
               for c in text):
            raise BundleError("text input contains unsupported control characters")
    return raw


def read_verified_input(project_root, entry):
    """Return bounded verified JSON/text input bytes; no execution or transmission."""
    return _read_input(_root(project_root), entry)


def _provenance(value):
    _keys(value, {"origin", "producer_revision", "model", "test_only"}, "provenance")
    for key, bound in (("origin", 240), ("producer_revision", 128), ("model", 160)):
        _text(value[key], bound, f"provenance.{key}")
    if type(value["test_only"]) is not bool:
        raise BundleError("provenance.test_only must be boolean")
    return value


def _references(value, available, label):
    refs = _array(value, 16, label)
    if len(refs) != len(set(_id(v, label) for v in refs)):
        raise BundleError(f"{label}: duplicate references")
    if any(ref not in available for ref in refs):
        raise BundleError(f"{label}: unresolved reference")
    return refs


def _directory_id(info):
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _reparse(info):
        raise BundleError("output parent is not an ordinary directory")
    return (info.st_dev, info.st_ino)


def _guard_output(project_root, project_identity, destination, directories, relative):
    project = _root(project_root)
    if _directory_id(project.lstat()) != project_identity:
        raise BundleError("project root changed during export")
    path = destination
    if _directory_id(path.lstat()) != directories[""]:
        raise BundleError("destination directory changed during export")
    parts = _path(relative)
    parent_key = []
    for part in parts[:-1]:
        parent_key.append(part)
        path = path / part
        key = "/".join(parent_key)
        if key not in directories or _directory_id(path.lstat()) != directories[key]:
            raise BundleError("output parent changed during export")
    return destination.joinpath(*parts)


def _verify_output(project, identity, destination, directories, relative, raw, expected=None):
    path = _guard_output(project, identity, destination, directories, relative)
    initial = path.lstat()
    if (not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode)
            or _reparse(initial) or initial.st_nlink != 1
            or (expected is not None and _signature(initial) != expected)):
        raise BundleError("output file changed/reparsed/linked")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if _signature(opened) != _signature(initial):
            raise BundleError("output changed before readback")
        actual = handle.read(MAX_FILE + 1)
        after = os.fstat(handle.fileno())
    path = _guard_output(project, identity, destination, directories, relative)
    current = path.lstat()
    if (actual != raw or _signature(after) != _signature(initial)
            or _signature(current) != _signature(initial)):
        raise BundleError("output readback mismatch; export incomplete")
    return _signature(current)


def _write_output(project, identity, destination, directories, relative, raw):
    path = _guard_output(project, identity, destination, directories, relative)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        opened = os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode) or _reparse(opened)
                or opened.st_nlink != 1):
            raise BundleError("created output is not a single-link regular file")
        if handle.write(raw) != len(raw):
            raise BundleError("partial output write")
        handle.flush()
        written = os.fstat(handle.fileno())
        if (written.st_size != len(raw) or written.st_nlink != 1
                or _reparse(written) or written.st_ino != opened.st_ino
                or written.st_dev != opened.st_dev):
            raise BundleError("output changed while writing")
    return _verify_output(project, identity, destination, directories, relative,
                          raw, _signature(written))


def export_bundle(project_root, directory_name, *, app_id, project_id, revision,
                  results, inputs, tests, provenance):
    """Create a fresh local export directory; do not transmit, execute or adopt.

    Results are app-owned review records. Test declarations are caller-supplied
    receipts, not independently rerun evidence. Inputs are copied only after
    exact size/hash/path and UTF-8 checks. Source files are never modified.
    """
    root = _root(project_root)
    root_identity = _directory_id(root.lstat())
    if len(_path(directory_name)) != 1:
        raise BundleError("destination must be one portable directory name")
    destination = root / directory_name
    if destination.exists():
        raise BundleError("destination already exists")
    if not isinstance(app_id, str) or app_id not in SCHEMAS:
        raise BundleError("unsupported app_id")
    _text(project_id, 128, "project_id")
    _text(revision, 128, "revision")
    _provenance(provenance)
    _array(results, 16, "results")
    _array(inputs, 16, "inputs")
    _array(tests, 32, "tests")
    files = {}
    artifact_records = []
    input_records = []
    test_records = []
    artifact_map = {}
    input_map = {}
    source_paths = set()

    for input_index, entry in enumerate(inputs, 1):
        raw = _read_input(root, entry)
        if entry["media_type"] == "application/json":
            decoded_input = _json(raw)
            if (isinstance(decoded_input, dict) and "project_id" in decoded_input
                    and decoded_input["project_id"] != project_id):
                raise BundleError("input project_id differs from export project")
        identity = entry["id"]
        if identity in input_map:
            raise BundleError("duplicate input id")
        if entry["path"].casefold() in source_paths:
            raise BundleError("duplicate source path")
        source_paths.add(entry["path"].casefold())
        suffix = ".json" if entry["media_type"] == "application/json" else ".txt"
        path = f"inputs/input-{input_index:02d}{suffix}"
        record = {**entry, "path": path}
        input_records.append(record)
        input_map[identity] = record
        files[path] = raw

    for artifact_index, item in enumerate(results, 1):
        _keys(item, {"id", "schema", "status", "result"}, "result record")
        identity = _id(item["id"], "artifact.id")
        if identity in artifact_map:
            raise BundleError("duplicate artifact id")
        if not isinstance(item["schema"], str) or item["schema"] not in SCHEMAS[app_id]:
            raise BundleError("unsupported typed result schema")
        _text(item["status"], 128, "artifact.status")
        result = item["result"]
        if (not isinstance(result, dict) or result.get("project_id") != project_id
                or result.get("revision") != revision):
            raise BundleError("result project/revision mismatch")
        if result.get("status") != item["status"]:
            raise BundleError("result status mismatch")
        if item["schema"].endswith(".reviewed-photo-inventory.v1"):
            if (result.get("original_image_bytes_in_bundle") is not False
                    or result.get("image_verification") != "unavailable"):
                raise BundleError("photo result must exclude original images")
        wrapper = {
            "format": item["schema"], "app_id": app_id,
            "project_id": project_id, "revision": revision,
            "status": item["status"], "provenance": provenance, "result": result,
        }
        raw = _encode(wrapper)
        path = f"artifacts/result-{artifact_index:02d}.json"
        record = {"id": identity, "path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                  "bytes": len(raw), "media_type": "application/json",
                  "schema": item["schema"]}
        artifact_records.append(record)
        artifact_map[identity] = record
        files[path] = raw

    test_ids = set()
    for test_index, item in enumerate(tests, 1):
        _keys(item, {"id", "status", "artifact_ids", "input_ids", "details"}, "test")
        identity = _id(item["id"], "test.id")
        if identity in test_ids:
            raise BundleError("duplicate test id")
        test_ids.add(identity)
        if not isinstance(item["status"], str) or item["status"] not in {"passed", "failed", "unrun"}:
            raise BundleError("unsupported test status")
        _text(item["details"], 4096, "test.details", multiline=True)
        artifact_ids = _references(item["artifact_ids"], artifact_map, "artifact_ids")
        input_ids = _references(item["input_ids"], input_map, "input_ids")
        receipt = {
            "format": RECEIPT_FORMAT, "app_id": app_id,
            "project_id": project_id, "revision": revision,
            "test_id": identity, "status": item["status"],
            "artifact_sha256s": {key: artifact_map[key]["sha256"] for key in artifact_ids},
            "input_sha256s": {key: input_map[key]["sha256"] for key in input_ids},
            "details": item["details"],
        }
        raw = _encode(receipt)
        path = f"receipts/test-{test_index:02d}.json"
        test_records.append({
            "id": identity, "status": item["status"],
            "artifact_ids": artifact_ids, "input_ids": input_ids,
            "receipt_path": path, "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "receipt_bytes": len(raw),
        })
        files[path] = raw

    bundle = {
        "format": FORMAT, "recipient": "aster", "app_id": app_id,
        "project_id": project_id, "revision": revision,
        "artifacts": artifact_records, "inputs": input_records, "tests": test_records,
    }
    files["bundle.json"] = _encode(bundle)
    if sum(len(raw) for raw in files.values()) > MAX_TOTAL:
        raise BundleError("total bundle files exceed 1 MiB")
    paths = list(files)
    if len(paths) != len({path.casefold() for path in paths}):
        raise BundleError("case-insensitive output path collision")
    for path in paths:
        _path(path)
        _path(f"{directory_name}/{path}")

    # Reserve one fresh directory. Revalidate ordinary parents and file handles
    # through creation/write/readback. There is no absolute race-proof guarantee:
    # consumers must recheck bytes/hashes and local writers must be serialized.
    if _directory_id(_root(root).lstat()) != root_identity:
        raise BundleError("project root changed before export creation")
    destination.mkdir()
    directories = {"": _directory_id(destination.lstat())}
    for folder in ("inputs", "artifacts", "receipts"):
        _guard_output(root, root_identity, destination, directories, f"{folder}.check")
        (destination / folder).mkdir()
        directories[folder] = _directory_id((destination / folder).lstat())
    signatures = {}
    for relative, raw in files.items():
        if relative == "bundle.json":
            # Check snapshots again immediately before publishing the manifest.
            for previous, signature in signatures.items():
                _verify_output(root, root_identity, destination, directories,
                               previous, files[previous], signature)
        signatures[relative] = _write_output(root, root_identity, destination,
                                             directories, relative, raw)
    for relative, signature in signatures.items():
        _verify_output(root, root_identity, destination, directories,
                       relative, files[relative], signature)
    return destination / "bundle.json"
