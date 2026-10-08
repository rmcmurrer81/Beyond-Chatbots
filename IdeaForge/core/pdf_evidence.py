"""Offline project-scoped PDF quotations; never included in provider context.

Source snapshots and version records are authoritative. Native strings are source
claims, not validated measurements. This module makes no network or model calls.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = "ideaforge.local-pdf.v1"
BACKEND_VERSION = "5.14.0"
MAX_MANIFEST_BYTES = 1_000_000
MAX_VERSIONS = 32
MAX_ACTIVE_SOURCES = 8
MAX_STORAGE_BYTES = 64_000_000
MAX_STORE_SOURCE_FILES = 32
MAX_STORE_VERSION_FILES = 32
QUOTE_NOTICE = ("Unaltered PDFium text-object extraction; Unicode mapping and "
                "visibility are not proof of source accuracy. Reading order, OCR, "
                "table relationships and CAD dimension validation are unsupported.")


class PDFEvidenceError(ValueError):
    """A bounded import/retrieval failed without changing the active manifest."""


@dataclass(frozen=True)
class Limits:
    file_bytes: int = 8_000_000
    pages: int = 25
    objects_per_page: int = 2000
    object_chars: int = 2000
    total_chars: int = 100_000
    result_bytes: int = 2_000_000
    seconds: float = 10.0

    def validate(self):
        caps = {"file_bytes": 8_000_000, "pages": 25, "objects_per_page": 2000,
                "object_chars": 2000, "total_chars": 100_000,
                "result_bytes": 2_000_000, "seconds": 30.0}
        for name, cap in caps.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PDFEvidenceError("Invalid import limit")
            if not 0 < value <= cap or (isinstance(value, float) and not math.isfinite(value)):
                raise PDFEvidenceError("Import limit outside supported bounds")
            if name != "seconds" and not isinstance(value, int):
                raise PDFEvidenceError("Count/byte limits must be integers")
        return self


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _read(path, maximum):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise PDFEvidenceError("Local PDF evidence file exceeds its byte budget")
    return raw


def _identity(root):
    root = Path(root).resolve(strict=True)
    data = json.loads(_read(_path(root, "project.json"), 4_000_000))
    if not isinstance(data, dict):
        raise PDFEvidenceError("Expected project object")
    identity = str(data.get("project_id") or "legacy-" + _sha(str(root).encode())[:24])
    if len(identity) > 128 or any(ord(c) < 32 for c in identity):
        raise PDFEvidenceError("Invalid project identity")
    return root, identity, _sha(str(root).encode())


def _path(root, relative):
    """Refuse symlinks/junction escapes, including existing parent directories."""
    root = Path(root)
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise PDFEvidenceError("PDF evidence path escaped its project")
    cursor = target
    while cursor != root:
        if cursor.is_symlink():
            raise PDFEvidenceError("PDF evidence paths must not be symlinks")
        cursor = cursor.parent
    return target


def _store(root):
    path = _path(root, "research/pdf_evidence")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _empty(identity, binding):
    return {"schema": SCHEMA, "project_id": identity, "root_binding": binding,
            "active": {}, "versions": []}


def _manifest(store, identity, binding):
    path = _path(store, "manifest.json")
    if not path.exists():
        return _empty(identity, binding)
    value = json.loads(_read(path, MAX_MANIFEST_BYTES))
    if (not isinstance(value, dict) or value.get("schema") != SCHEMA or
            value.get("project_id") != identity or value.get("root_binding") != binding):
        raise PDFEvidenceError("Manifest belongs to a different project or location")
    active, versions = value.get("active"), value.get("versions")
    if (not isinstance(active, dict) or len(active) > MAX_ACTIVE_SOURCES or
            not isinstance(versions, list) or len(versions) > MAX_VERSIONS):
        raise PDFEvidenceError("Invalid or over-budget PDF manifest")
    seen = {}
    for item in versions:
        if not isinstance(item, dict):
            raise PDFEvidenceError("Invalid version entry")
        for name in ("source_id", "version_id"):
            if not re.fullmatch(r"[0-9a-f]{32}", str(item.get(name, ""))):
                raise PDFEvidenceError("Invalid source/version identifier")
        for name in ("source_sha256", "record_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(name, ""))):
                raise PDFEvidenceError("Invalid source/record digest")
        if item["version_id"] in seen:
            raise PDFEvidenceError("Duplicate PDF version")
        seen[item["version_id"]] = item["source_id"]
    if any(seen.get(version) != source for source, version in active.items()):
        raise PDFEvidenceError("Invalid active PDF binding")
    return value


@contextmanager
def _lock(store):
    path = _path(store, ".import-lock")
    try:
        path.mkdir()
    except FileExistsError as exc:
        raise PDFEvidenceError("PDF import already locked; inspect an interrupted import") from exc
    try:
        yield
    finally:
        path.rmdir()


def _atomic(path, raw):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".manifest-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _immutable(path, raw):
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if _read(path, max(len(raw), 1)) != raw:
            raise PDFEvidenceError("Immutable PDF evidence snapshot was altered")


def _storage_bytes(store, deadline, additions=None):
    """Bound enumeration even when interrupted imports leave orphan records."""
    _check_deadline(deadline)
    additions = additions or {}
    allowed_root = {"sources", "versions", "manifest.json", ".import-lock"}
    with os.scandir(store) as entries:
        for number, entry in enumerate(entries, 1):
            _check_deadline(deadline)
            item = Path(entry.path)
            if number > len(allowed_root) or item.name not in allowed_root:
                raise PDFEvidenceError("Interrupted/unexpected PDF store files require manual recovery")
            _path(store, item.relative_to(store))
    total = 0
    for folder, cap, pattern in (
            ("sources", MAX_STORE_SOURCE_FILES, r"[0-9a-f]{64}\.pdf"),
            ("versions", MAX_STORE_VERSION_FILES, r"[0-9a-f]{32}\.json")):
        _check_deadline(deadline)
        path = _path(store, folder)
        if path.exists():
            with os.scandir(path) as entries:
                for number, entry in enumerate(entries, 1):
                    _check_deadline(deadline)
                    if number + additions.get(folder, 0) > cap:
                        raise PDFEvidenceError("PDF store entry budget reached; inspect orphan records")
                    item = Path(entry.path)
                    _path(store, item.relative_to(store))
                    if not item.is_file() or not re.fullmatch(pattern, item.name):
                        raise PDFEvidenceError("Unexpected PDF store entry")
                    total += item.stat().st_size
                    _check_deadline(deadline)
                    if total > MAX_STORAGE_BYTES:
                        raise PDFEvidenceError("Project PDF storage budget reached")
    return total


def _check_deadline(deadline):
    if time.monotonic() > deadline:
        raise PDFEvidenceError("PDF operation exceeded its elapsed-time budget")


def _box(value):
    if (not isinstance(value, list) or len(value) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                abs(v) > 1_000_000_000 or not math.isfinite(v) for v in value) or
            value[0] >= value[2] or value[1] >= value[3]):
        raise PDFEvidenceError("Invalid native PDF bounding box")
    return value


def _validate_report(report, digest, limits):
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA or
            report.get("source_sha256") != digest):
        raise PDFEvidenceError("Extraction report/source mismatch")
    backend = report.get("backend")
    if (not isinstance(backend, dict) or backend.get("package") != "pypdfium2" or
            backend.get("version") != BACKEND_VERSION or
            not isinstance(backend.get("pdfium_version"), str) or
            len(backend["pdfium_version"]) > 200):
        raise PDFEvidenceError("Unsupported extraction backend")
    pages = report.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= limits.pages:
        raise PDFEvidenceError("Invalid extraction page count")
    total_chars = total_passages = 0
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or page.get("page") != number or
                isinstance(page.get("page"), bool) or page.get("rotation") != 0):
            raise PDFEvidenceError("Invalid native page metadata")
        page_box = _box(page.get("bbox"))
        if page_box[0] != 0 or page_box[1] != 0:
            raise PDFEvidenceError("Nonzero page origin unsupported")
        passages = page.get("passages")
        if not isinstance(passages, list) or len(passages) > limits.objects_per_page:
            raise PDFEvidenceError("Invalid native object count")
        expected_status = ("native_text_present" if passages else
                           "no_extractable_native_text_unsupported_image_or_blank")
        if page.get("native_text_status") != expected_status:
            raise PDFEvidenceError("Missing or inconsistent native page support status")
        indices = set()
        for passage in passages:
            if not isinstance(passage, dict):
                raise PDFEvidenceError("Invalid native passage")
            index, text = passage.get("object_index"), passage.get("text")
            if (isinstance(index, bool) or not isinstance(index, int) or
                    not 0 <= index < limits.objects_per_page or index in indices or
                    not isinstance(text, str) or not text or
                    len(text) > limits.object_chars):
                raise PDFEvidenceError("Invalid native object identity/text")
            text.encode("utf-8", errors="strict")
            indices.add(index)
            box = _box(passage.get("bbox"))
            if (box[0] < page_box[0] or box[1] < page_box[1] or
                    box[2] > page_box[2] or box[3] > page_box[3]):
                raise PDFEvidenceError("Cropped or partly clipped native object unsupported")
            total_chars += len(text)
            total_passages += 1
    if total_chars > limits.total_chars:
        raise PDFEvidenceError("Native text character budget exceeded")
    if not total_passages:
        raise PDFEvidenceError("No extractable native text; scanned/image-only content unsupported")
    return report


def _run_worker(source, output, limits, seconds):
    """Hard deadline owns one worker; never enumerates/kills unrelated processes."""
    worker = Path(__file__).with_name("pdf_worker.py")
    process = subprocess.Popen(
        [sys.executable, "-I", str(worker), str(source), str(output),
         json.dumps(asdict(limits))],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.wait(timeout=max(.001, seconds))
    except subprocess.TimeoutExpired as exc:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired as shutdown:
            raise PDFEvidenceError("Owned PDF worker termination could not be confirmed") from shutdown
        raise PDFEvidenceError("Native PDF worker exceeded its hard deadline") from exc
    if not output.exists():
        raise PDFEvidenceError("Native PDF worker failed without a valid report")
    payload = json.loads(_read(output, limits.result_bytes))
    if process.returncode or not payload.get("ok"):
        # Worker errors contain controlled status codes, never source text.
        code = payload.get("error", "native_extraction_failed")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,80}", code):
            code = "native_extraction_failed"
        raise PDFEvidenceError(code)
    return payload["report"]


def _citation(identity, version, page, passage):
    value = [identity, version, page, passage["object_index"],
             passage["text"], passage["bbox"]]
    return "IF-PDF-" + _sha(_json_bytes(value))[:32]


def ingest_pdf(project_root, source_path, *, source_id=None, title="", limits=None):
    """Explicit local import; replacement preserves old versions and snapshots."""
    limits = (limits or Limits()).validate()
    deadline = time.monotonic() + limits.seconds
    root, identity, binding = _identity(project_root)
    source = Path(source_path)
    if source.is_symlink() or not source.is_file():
        raise PDFEvidenceError("Import requires a regular local PDF file")
    raw = _read(source, limits.file_bytes)
    if not raw.startswith(b"%PDF-"):
        raise PDFEvidenceError("Import requires PDF bytes")
    digest = _sha(raw)
    if not isinstance(title, str) or len(title) > 300:
        raise PDFEvidenceError("Invalid PDF title")
    if source_id is not None and not re.fullmatch(r"[0-9a-f]{32}", str(source_id)):
        raise PDFEvidenceError("Invalid source identifier")
    store = _store(root)
    with _lock(store):
        manifest = _manifest(store, identity, binding)
        if len(manifest["versions"]) >= MAX_VERSIONS:
            raise PDFEvidenceError("PDF version budget reached")
        if source_id is not None and source_id not in manifest["active"]:
            raise PDFEvidenceError("Replacement source must belong to this project")
        source_id = source_id or uuid.uuid4().hex
        if source_id not in manifest["active"] and len(manifest["active"]) >= MAX_ACTIVE_SOURCES:
            raise PDFEvidenceError("Active PDF source budget reached")
        with tempfile.TemporaryDirectory(dir=store, prefix=".extract-") as temporary:
            snapshot, output = Path(temporary) / "source.pdf", Path(temporary) / "result.json"
            snapshot.write_bytes(raw)
            _check_deadline(deadline)
            report = _run_worker(snapshot, output, limits, deadline - time.monotonic())
            _validate_report(report, digest, limits)
        _check_deadline(deadline)
        version = uuid.uuid4().hex
        record = {"schema": SCHEMA, "project_id": identity, "root_binding": binding,
                  "source_id": source_id, "version_id": version,
                  "original_name": source.name[:300], "title": title,
                  "source_bytes": len(raw), "source_sha256": digest,
                  "limits": asdict(limits), "report": report, "notice": QUOTE_NOTICE}
        for page in report["pages"]:
            for passage in page["passages"]:
                passage["citation"] = _citation(identity, version, page["page"], passage)
        record_raw = _json_bytes(record)
        if len(record_raw) > limits.result_bytes:
            raise PDFEvidenceError("Stored extraction record exceeds its byte budget")
        source_target = _path(store, f"sources/{digest}.pdf")
        additions = {"sources": 0 if source_target.exists() else 1, "versions": 1}
        if _storage_bytes(store, deadline, additions) + len(raw) + len(record_raw) > MAX_STORAGE_BYTES:
            raise PDFEvidenceError("Project PDF storage budget reached")
        for folder in ("sources", "versions"):
            _path(store, folder).mkdir(exist_ok=True)
        _immutable(_path(store, f"sources/{digest}.pdf"), raw)
        _immutable(_path(store, f"versions/{version}.json"), record_raw)
        manifest["versions"].append({"source_id": source_id, "version_id": version,
                                     "source_sha256": digest, "record_sha256": _sha(record_raw)})
        manifest["active"][source_id] = version
        manifest_raw = _json_bytes(manifest)
        if len(manifest_raw) > MAX_MANIFEST_BYTES:
            raise PDFEvidenceError("PDF manifest byte budget reached")
        _check_deadline(deadline)
        _atomic(_path(store, "manifest.json"), manifest_raw)
    return {"source_id": source_id, "version_id": version, "source_sha256": digest,
            "pages": len(report["pages"]), "status": "local_native_quotations",
            "page_support": [{"page": p["page"], "status": p["native_text_status"]}
                             for p in report["pages"]],
            "notice": QUOTE_NOTICE}


def _retrieval_deadline(seconds):
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or
            not 0 < seconds <= 5 or (isinstance(seconds, float) and not math.isfinite(seconds))):
        raise PDFEvidenceError("Invalid retrieval time budget")
    return time.monotonic() + seconds


def _records(project_root, *, include_history=False, seconds=2.0, deadline=None):
    own_deadline = _retrieval_deadline(seconds)
    deadline = own_deadline if deadline is None else min(deadline, own_deadline)
    root, identity, binding = _identity(project_root)
    store = _path(root, "research/pdf_evidence")
    if not store.exists():
        _check_deadline(deadline)
        return
    manifest = _manifest(store, identity, binding)
    active = set(manifest["active"].values())
    for item in manifest["versions"]:
        if not include_history and item["version_id"] not in active:
            continue
        _check_deadline(deadline)
        raw = _read(_path(store, f'versions/{item["version_id"]}.json'), 2_000_000)
        if _sha(raw) != item["record_sha256"]:
            raise PDFEvidenceError("Extraction record hash mismatch")
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get("project_id") != identity or
                record.get("root_binding") != binding or record.get("schema") != SCHEMA or
                record.get("version_id") != item["version_id"] or
                record.get("source_id") != item["source_id"] or
                record.get("source_sha256") != item["source_sha256"]):
            raise PDFEvidenceError("Extraction record/project mismatch")
        source_raw = _read(_path(store, f'sources/{item["source_sha256"]}.pdf'), 8_000_000)
        if _sha(source_raw) != item["source_sha256"] or len(source_raw) != record.get("source_bytes"):
            raise PDFEvidenceError("Preserved PDF snapshot hash/length mismatch")
        limits = Limits(**record["limits"]).validate()
        _validate_report(record["report"], item["source_sha256"], limits)
        _check_deadline(deadline)
        for page in record["report"]["pages"]:
            _check_deadline(deadline)
            for passage in page["passages"]:
                _check_deadline(deadline)
                citation = _citation(identity, item["version_id"], page["page"], passage)
                if passage.get("citation") != citation:
                    raise PDFEvidenceError("Citation metadata was altered")
                yield {"project_id": identity, "source_id": item["source_id"],
                       "version_id": item["version_id"], "active": item["version_id"] in active,
                       "source_sha256": item["source_sha256"],
                       "original_name": record["original_name"], "title": record["title"],
                       "page": page["page"], "page_bbox": page["bbox"],
                       "page_rotation": page["rotation"],
                       "native_text_status": page["native_text_status"],
                       "coordinate_system": "PDF user space; left,bottom,right,top",
                       "object_index": passage["object_index"], "bbox": passage["bbox"],
                       "passage": passage["text"], "citation": citation,
                       "kind": "local_native_pdf_object_unverified_source_claim",
                       "notice": QUOTE_NOTICE}


def retrieve_pdf(project_root, query, *, limit=6, seconds=2.0):
    """Deterministic literal token search, entirely local; no synthesized answer."""
    if not isinstance(query, str) or len(query) > 2000:
        raise PDFEvidenceError("Invalid local PDF query")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 6:
        raise PDFEvidenceError("Local PDF retrieval limit must be 0..6")
    deadline = _retrieval_deadline(seconds)
    tokens = set(re.findall(r"\w+", query.lower())) - {"a", "an", "the", "is", "what", "of"}
    if not tokens or not limit:
        _check_deadline(deadline)
        return []
    ranked = []
    for row in _records(project_root, seconds=seconds, deadline=deadline):
        _check_deadline(deadline)
        words = set(re.findall(r"\w+", row["passage"].lower()))
        score = len(tokens & words)
        if score:
            ranked.append((score, row["citation"], row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    _check_deadline(deadline)
    return [item[2] for item in ranked[:limit]]


def resolve_pdf_citation(project_root, citation, *, seconds=2.0):
    """History resolves against preserved bytes, with active=False after replacement."""
    if not isinstance(citation, str) or not re.fullmatch(r"IF-PDF-[0-9a-f]{32}", citation):
        return None
    deadline = _retrieval_deadline(seconds)
    for row in _records(project_root, include_history=True, seconds=seconds, deadline=deadline):
        _check_deadline(deadline)
        if row["citation"] == citation:
            return row
    _check_deadline(deadline)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import")
    importer.add_argument("pdf", type=Path)
    importer.add_argument("--source-id")
    importer.add_argument("--title", default="")
    importer.add_argument("--max-pages", type=int, default=25)
    importer.add_argument("--seconds", type=float, default=10)
    search = sub.add_parser("retrieve")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=6)
    resolver = sub.add_parser("resolve")
    resolver.add_argument("citation")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            result = ingest_pdf(args.project, args.pdf, source_id=args.source_id,
                                title=args.title, limits=Limits(pages=args.max_pages,
                                                                seconds=args.seconds))
        elif args.command == "retrieve":
            result = retrieve_pdf(args.project, args.query, limit=args.limit)
        else:
            result = resolve_pdf_citation(args.project, args.citation)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (PDFEvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        # Controlled API errors; native stderr/source bytes never forwarded.
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
