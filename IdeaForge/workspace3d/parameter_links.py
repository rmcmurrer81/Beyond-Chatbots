"""Local user-reviewed PDF-to-parameter annotations; never writes design scenes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from core import pdf_evidence as pdf
from .model import digest, validate
from .store import Store

SCHEMA = "ideaforge.reviewed-parameter-link.v1"
RECEIPT_SCHEMA = "ideaforge.parameter-link-test.v1"
MAX_LINKS = 256
MAX_EVENTS = 1024
MAX_RECEIPTS = 512
MAX_JSON_BYTES = 24_000
MAX_DB_BYTES = 16_000_000
NOTICE = ("User-reviewed source claim linked to an existing parameter. This is "
          "not dimensional certification, physical validation or permission to "
          "change CAD. OCR, table relationships and unit conversion unsupported.")


class LinkError(ValueError):
    pass


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise LinkError("Missing or unknown fields")


def _text(value, maximum=500):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum or
            any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise LinkError("Invalid bounded text")
    value.encode("utf-8", errors="strict")
    return value


def _hex(value, length):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise LinkError("Invalid digest or identifier")
    return value


def _review(review):
    _keys(review, ("confirmed", "reviewer", "reviewed_at", "rationale"))
    if review["confirmed"] is not True:
        raise LinkError("An explicit user review is required")
    _text(review["reviewer"], 128)
    _text(review["rationale"], 1000)
    timestamp = _text(review["reviewed_at"], 40)
    try:
        stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LinkError("Review time requires an explicit UTC offset") from exc
    if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
        raise LinkError("Review time requires UTC")
    return review


def _raw(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_JSON_BYTES:
        raise LinkError("Annotation/receipt exceeds byte budget")
    return raw


def _stored_blob(value):
    if type(value) is not bytes or not 1 <= len(value) <= MAX_JSON_BYTES:
        raise LinkError("Stored annotation/receipt must be bounded bytes")
    return value


def strict_json(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_JSON_BYTES:
        raise LinkError("Expected bounded UTF-8 JSON bytes")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LinkError("Duplicate JSON field")
            result[key] = value
        return result
    def constant(_):
        raise LinkError("Nonfinite JSON numbers unsupported")
    try:
        return json.loads(raw.decode("utf-8", errors="strict"),
                          object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LinkError("Invalid UTF-8 JSON") from exc


def _parameter(scene, parameter):
    _keys(parameter, ("part_id", "field", "index"))
    _text(parameter["part_id"], 64)
    matches = [p for p in scene["parts"] if p["id"] == parameter["part_id"]]
    if len(matches) != 1:
        raise LinkError("Parameter part does not exist in this revision")
    part, field, index = matches[0], parameter["field"], parameter["index"]
    if field in ("size_mm", "position_mm", "rotation_deg"):
        if type(index) is not int or index not in (0, 1, 2):
            raise LinkError("Vector parameter requires index 0..2")
        return part[field][index], "deg" if field == "rotation_deg" else "mm"
    if field in ("joint.min_deg", "joint.max_deg", "joint.angle_deg"):
        if index is not None or not isinstance(part.get("joint"), dict):
            raise LinkError("Joint scalar parameter requires an existing joint")
        return part["joint"][field.split(".")[1]], "deg"
    raise LinkError("Unsupported parameter; choose an existing dimension or angle")


def _selection(source, selection, expected_value, expected_unit):
    _keys(selection, ("start", "quote", "numeric_text", "unit"))
    start, quote = selection["start"], _text(selection["quote"], 100)
    numeric, unit = _text(selection["numeric_text"], 30), selection["unit"]
    if type(start) is not int or not 0 <= start < len(source["passage"]):
        raise LinkError("Numeric quote requires an exact native string offset")
    if unit != expected_unit:
        raise LinkError("Source unit and parameter unit differ; conversion unsupported")
    if not re.fullmatch(r"[+-]?[0-9]{1,9}(?:\.[0-9]{1,12})?", numeric):
        raise LinkError("Expected bounded plain decimal numeric spelling")
    if not re.fullmatch(re.escape(numeric) + r"[ \t]{0,4}" + re.escape(unit), quote):
        raise LinkError("Quote must contain exactly the numeric spelling and unit")
    end = start + len(quote)
    text = source["passage"]
    if text[start:end] != quote:
        raise LinkError("Quote/offset does not match exact native passage")
    # Prevent selecting 20 mm inside 120 mm, or mm inside mm2/mm².
    if ((start and (text[start-1].isalnum() or text[start-1] in ".,+-/")) or
            (end < len(text) and (text[end].isalnum() or text[end] in "_"))):
        raise LinkError("Numeric quote boundaries are ambiguous")
    try:
        value = Decimal(numeric)
        parameter_value = Decimal(str(expected_value))
    except InvalidOperation as exc:
        raise LinkError("Invalid decimal") from exc
    if (not value.is_finite() or abs(value) > 1_000_000 or
            value != parameter_value):
        raise LinkError("Quoted numeric value differs from existing parameter")
    suffix = text[end:]
    if (re.match(r"\s*[/^*·×²³⁻⁺]", suffix) or
            re.match(r"\s+(?:per\b|[A-Za-zµμ]+\s*(?:\^\s*[+-]?\s*[0-9]+|[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+|[+−-]\s*[0-9]+)|[xX]\s+(?:mm|cm|m|s|deg)\b)", suffix)):
        raise LinkError("Compound or powered units are unsupported")
    return selection


def _source(source, project_id):
    _keys(source, ("project_id", "source_id", "version_id", "citation", "source_sha256",
                  "page", "bbox", "object_index", "passage", "coordinate_system"))
    if source["project_id"] != project_id:
        raise LinkError("Source belongs to a different project")
    for key in ("source_id", "version_id"):
        _hex(source[key], 32)
    _hex(source["source_sha256"], 64)
    if (not isinstance(source["citation"], str) or
            not re.fullmatch(r"IF-PDF-[0-9a-f]{32}", source["citation"]) or
            type(source["page"]) is not int or not 1 <= source["page"] <= 25 or
            type(source["object_index"]) is not int or not 0 <= source["object_index"] < 2000 or
            source["coordinate_system"] != "PDF user space; left,bottom,right,top"):
        raise LinkError("Invalid exact source metadata")
    _text(source["passage"], 2000)
    pdf._box(source["bbox"])
    return source


def _parameter_spec(parameter, unit):
    _keys(parameter, ("part_id", "field", "index"))
    _text(parameter["part_id"], 64)
    field, index = parameter["field"], parameter["index"]
    if field in ("size_mm", "position_mm", "rotation_deg"):
        if type(index) is not int or index not in (0, 1, 2):
            raise LinkError("Invalid parameter index")
        expected = "deg" if field == "rotation_deg" else "mm"
    elif field in ("joint.min_deg", "joint.max_deg", "joint.angle_deg") and index is None:
        expected = "deg"
    else:
        raise LinkError("Unsupported parameter field")
    if unit != expected:
        raise LinkError("Stored parameter unit differs from field")


def _receipt(receipt, record, record_hash):
    _keys(receipt, ("schema", "id", "project_id", "revision", "scene_hash",
                    "source_sha256", "link_sha256", "status", "command", "observations",
                    "run_at", "review"))
    _review(receipt["review"])
    _text(receipt["id"], 100)
    _text(receipt["command"], 1000)
    _text(receipt["observations"], 2000)
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["status"] not in ("passed", "failed", "unrun"):
        raise LinkError("Invalid test receipt schema/status")
    if receipt["status"] == "unrun":
        if receipt["run_at"] is not None:
            raise LinkError("Unrun receipt must not claim an execution time")
    else:
        _review({"confirmed": True, "reviewer": "receipt", "reviewed_at": receipt["run_at"],
                 "rationale": "execution timestamp"})
    expected = {"project_id": record["project_id"], "revision": record["revision"],
                "scene_hash": record["scene_hash"],
                "source_sha256": record["source"]["source_sha256"], "link_sha256": record_hash}
    if any(receipt[k] != value for k, value in expected.items()):
        raise LinkError("Test receipt belongs to different evidence")
    return receipt


def _source_binding(row):
    return {k: row[k] for k in ("project_id", "source_id", "version_id", "citation",
                                "source_sha256", "page", "bbox", "object_index",
                                "passage", "coordinate_system")}


def _database_path(root, relative):
    path = pdf._path(root, relative)
    # SQLite can open these standard sidecars independently of the main DB.
    for suffix in ("", "-journal", "-wal", "-shm"):
        target = pdf._path(root, relative + suffix)
        cursor = target
        while True:
            if cursor.exists():
                info = cursor.lstat()
                if (stat.S_ISLNK(info.st_mode) or
                        getattr(info, "st_file_attributes", 0) & 0x400):
                    raise LinkError("Database paths must not use symlinks or reparse points")
                if cursor == target and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    raise LinkError("Database/sidecar must be a regular file with one hard link")
            if cursor == root:
                break
            cursor = cursor.parent
    return path


class ParameterLinks:
    """Separate durable annotation ledger over the existing Store revisions.

    No method calls Store.add/accept or writes geometry. Human confirmation is an
    operator assertion recorded locally, not an authenticated identity service.
    """
    def __init__(self, project_root):
        self.root, self.project_id, self.root_binding = pdf._identity(project_root)
        history = _database_path(self.root, "workspace3d/history.sqlite3")
        if not history.is_file():
            raise LinkError("Create a design revision with the existing Store first")
        self.scene_store = Store(self.root)
        self.path = _database_path(self.root, "workspace3d/parameter_links.sqlite3")
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS links (
                    id TEXT PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    link_id TEXT NOT NULL, active INTEGER NOT NULL,
                    previous_active INTEGER NOT NULL, undo_of TEXT,
                    review BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                    id TEXT PRIMARY KEY, link_id TEXT NOT NULL,
                    payload BLOB NOT NULL, sha256 TEXT NOT NULL);
            """)
            wanted = {"schema": SCHEMA, "project_id": self.project_id,
                      "root_binding": self.root_binding}
            current = dict(db.execute("SELECT key,value FROM metadata").fetchall())
            if current and current != wanted:
                raise LinkError("Annotation ledger belongs to a different project/location")
            if not current:
                if any(db.execute("SELECT 1 FROM " + t + " LIMIT 1").fetchone()
                       for t in ("links", "events", "receipts")):
                    raise LinkError("Annotation ledger identity is missing")
                db.executemany("INSERT INTO metadata VALUES (?,?)", wanted.items())

    @contextmanager
    def _db(self):
        _database_path(self.root, "workspace3d/parameter_links.sqlite3")
        root, identity, binding = pdf._identity(self.root)
        if identity != self.project_id or binding != self.root_binding:
            raise LinkError("Current project identity changed")
        if self.path.exists() and self.path.stat().st_size > MAX_DB_BYTES:
            raise LinkError("Annotation ledger exceeds byte budget")
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            yield db
            wanted = {"schema": SCHEMA, "project_id": self.project_id, "root_binding": self.root_binding}
            current = dict(db.execute("SELECT key,value FROM metadata").fetchall())
            if current != wanted:
                raise LinkError("Annotation ledger identity mismatch")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def _scene(self, revision, *, writing=False):
        _hex(revision, 32)
        _database_path(self.root, "workspace3d/history.sqlite3")
        root, identity, binding = pdf._identity(self.root)
        if identity != self.project_id or binding != self.root_binding:
            raise LinkError("Current project identity changed")
        # Existing Store connection and immutable revision schema; a short write
        # lock serializes annotations against Store.add without changing a scene.
        with self.scene_store.connection() as db:
            db.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
            row = db.execute("SELECT scene,tests FROM revisions WHERE id=?",
                             (revision,)).fetchone()
            latest = self.scene_store._pointer(db, "latest")
            if not row:
                raise LinkError("Design revision is missing")
            scene = validate(strict_scene_json(row["scene"]))
            scene_hash = digest(scene)
            tests = strict_scene_json(row["tests"])
            if not isinstance(tests, dict) or tests.get("scene_hash") != scene_hash:
                raise LinkError("Stored scene test hash does not match revision")
            yield scene, scene_hash, latest

    def _budget(self, db, table, cap):
        if db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] >= cap:
            raise LinkError("Annotation ledger record budget reached")

    def _record(self, db, link_id):
        _hex(link_id, 32)
        row = db.execute("SELECT payload,sha256 FROM links WHERE id=?", (link_id,)).fetchone()
        if not row:
            raise LinkError("Unknown parameter link")
        raw = _stored_blob(row["payload"])
        if pdf._sha(raw) != row["sha256"]:
            raise LinkError("Annotation record hash mismatch")
        record = strict_json(raw)
        _keys(record, ("schema", "id", "project_id", "root_binding", "revision",
                       "scene_hash", "parameter", "parameter_value", "parameter_unit",
                       "source", "selection", "review", "notice"))
        if (record["schema"] != SCHEMA or record["id"] != link_id or
                record["project_id"] != self.project_id or
                record["root_binding"] != self.root_binding):
            raise LinkError("Annotation record identity mismatch")
        _hex(record["revision"], 32)
        _hex(record["scene_hash"], 64)
        _source(record["source"], self.project_id)
        _review(record["review"])
        if (type(record["parameter_value"]) not in (int, float) or
                abs(record["parameter_value"]) > 1_000_000 or
                not math.isfinite(record["parameter_value"])):
            raise LinkError("Invalid stored parameter numeric value")
        _parameter_spec(record["parameter"], record["parameter_unit"])
        _selection(record["source"], record["selection"], record["parameter_value"], record["parameter_unit"])
        if record["notice"] != NOTICE:
            raise LinkError("Annotation notice was changed")
        return record, row["sha256"]

    @staticmethod
    def _active(db, link_id):
        row = db.execute("SELECT active,previous_active,review FROM events WHERE link_id=? ORDER BY seq DESC LIMIT 1",
                         (link_id,)).fetchone()
        if row is None or row[0] not in (0, 1) or row[1] not in (0, 1):
            raise LinkError("Annotation state event is missing")
        _review(strict_json(_stored_blob(row[2])))
        return bool(row[0])

    def _event(self, db, link_id, active, previous, review, undo_of=None):
        self._budget(db, "events", MAX_EVENTS)
        event_id = uuid.uuid4().hex
        db.execute("INSERT INTO events(id,link_id,active,previous_active,undo_of,review) "
                   "VALUES (?,?,?,?,?,?)",
                   (event_id, link_id, int(active), int(previous), undo_of, _raw(_review(review))))
        return event_id

    def create(self, request):
        _keys(request, ("schema", "project_id", "revision", "scene_hash", "parameter",
                        "source", "selection", "review"))
        if request["schema"] != SCHEMA or request["project_id"] != self.project_id:
            raise LinkError("Request schema/project mismatch")
        _hex(request["scene_hash"], 64)
        _review(request["review"])
        source = _source(request["source"], self.project_id)
        # The PDF import lock prevents replacement during this bounded local commit.
        pdf_store = pdf._path(self.root, "research/pdf_evidence")
        if not pdf_store.is_dir():
            raise LinkError("PDF evidence is missing")
        with pdf._lock(pdf_store), self._scene(request["revision"], writing=True) as snapshot:
            scene, scene_hash, latest = snapshot
            if latest != request["revision"] or scene_hash != request["scene_hash"]:
                raise LinkError("Review requires the exact current design revision/hash")
            row = pdf.resolve_pdf_citation(self.root, source["citation"])
            if row is None or not row["active"] or _raw(_source_binding(row)) != _raw(source):
                raise LinkError("Exact current PDF evidence is missing or differs")
            parameter_value, unit = _parameter(scene, request["parameter"])
            _selection(source, request["selection"], parameter_value, unit)
            link_id = uuid.uuid4().hex
            record = dict(request)
            record.update(id=link_id, root_binding=self.root_binding,
                          parameter_value=parameter_value, parameter_unit=unit, notice=NOTICE)
            raw = _raw(record)
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                # Exact repeated confirmations are idempotent while the link is active.
                signature = digest(request)
                for existing in db.execute("SELECT id FROM links ORDER BY id LIMIT ?", (MAX_LINKS,)):
                    prior, _ = self._record(db, existing[0])
                    comparison = {k: prior[k] for k in request}
                    if digest(comparison) == signature and self._active(db, prior["id"]):
                        event = db.execute("SELECT id FROM events WHERE link_id=? ORDER BY seq DESC LIMIT 1",
                                           (prior["id"],)).fetchone()[0]
                        return {"link_id": prior["id"], "event_id": event, "idempotent": True}
                self._budget(db, "links", MAX_LINKS)
                db.execute("INSERT INTO links VALUES (?,?,?)", (link_id, raw, pdf._sha(raw)))
                event = self._event(db, link_id, True, False, request["review"])
                return {"link_id": link_id, "event_id": event, "idempotent": False}

    def withdraw(self, link_id, review):
        _review(review)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._record(db, link_id)
            if not self._active(db, link_id):
                raise LinkError("Link is already withdrawn")
            return self._event(db, link_id, False, True, review)

    def undo(self, expected_event, review):
        """Reverse only the last ledger event; original records remain immutable."""
        _hex(expected_event, 32)
        _review(review)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            if not row or row["id"] != expected_event:
                raise LinkError("Ledger changed; review the newest action before undo")
            self._record(db, row["link_id"])
            _review(strict_json(_stored_blob(row["review"])))
            if row["active"] not in (0, 1) or row["previous_active"] not in (0, 1):
                raise LinkError("Invalid annotation state event")
            if bool(row["active"]) != self._active(db, row["link_id"]):
                raise LinkError("Annotation state is inconsistent")
            return self._event(db, row["link_id"], bool(row["previous_active"]),
                               bool(row["active"]), review, expected_event)

    def inspect(self, link_id):
        with self._db() as db:
            record, record_hash = self._record(db, link_id)
            active = self._active(db, link_id)
            receipts = []
            for row in db.execute("SELECT payload,sha256 FROM receipts WHERE link_id=? ORDER BY id LIMIT ?",
                                  (link_id, MAX_RECEIPTS)):
                raw = _stored_blob(row["payload"])
                if pdf._sha(raw) != row["sha256"]:
                    raise LinkError("Test receipt hash mismatch")
                receipts.append(_receipt(strict_json(raw), record, record_hash))
        reasons = []
        if not active:
            status = "withdrawn"
        else:
            unknown, stale = False, False
            with ExitStack() as stack:
                try:
                    pdf_store = pdf._path(self.root, "research/pdf_evidence")
                    if pdf_store.is_dir():
                        stack.enter_context(pdf._lock(pdf_store))
                except (pdf.PDFEvidenceError, OSError):
                    unknown = True
                    reasons.append("source_snapshot_busy_or_invalid")
                try:
                    snapshot = stack.enter_context(self._scene(record["revision"]))
                    scene, scene_hash, latest = snapshot
                    if scene_hash != record["scene_hash"] or latest != record["revision"]:
                        stale = True
                        reasons.append("design_revision_changed")
                    value, unit = _parameter(scene, record["parameter"])
                    if value != record["parameter_value"] or unit != record["parameter_unit"]:
                        stale = True
                        reasons.append("parameter_changed")
                    _selection(record["source"], record["selection"], value, unit)
                except (LinkError, ValueError, sqlite3.Error, OSError, TypeError, KeyError, OverflowError, RecursionError):
                    unknown = True
                    reasons.append("design_evidence_missing_or_invalid")
                try:
                    row = pdf.resolve_pdf_citation(self.root, record["source"]["citation"])
                    if row is None:
                        unknown = True
                        reasons.append("source_evidence_missing")
                    elif not row["active"]:
                        stale = True
                        reasons.append("source_version_replaced")
                    elif _raw(_source_binding(row)) != _raw(record["source"]):
                        unknown = True
                        reasons.append("source_evidence_differs")
                except (pdf.PDFEvidenceError, ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError):
                    unknown = True
                    reasons.append("source_evidence_missing_or_invalid")
                status = "unknown" if unknown else "stale" if stale else "current"
        return {"record": record, "record_sha256": record_hash, "status": status,
                "reasons": reasons, "tests": [
                    {"receipt": receipt,
                     "evidence_status": "current" if status == "current" else status}
                    for receipt in receipts], "notice": NOTICE}

    def attach_test_receipt(self, link_id, receipt):
        """Record an explicit local receipt; this function never executes a test."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            record, record_hash = self._record(db, link_id)
            _receipt(receipt, record, record_hash)
            raw = _raw(receipt)
            previous = db.execute("SELECT payload FROM receipts WHERE id=?", (receipt["id"],)).fetchone()
            if previous:
                if _stored_blob(previous[0]) != raw:
                    raise LinkError("Test receipt ID already has different immutable evidence")
                return receipt["id"]
            self._budget(db, "receipts", MAX_RECEIPTS)
            db.execute("INSERT INTO receipts VALUES (?,?,?,?)",
                       (receipt["id"], link_id, raw, pdf._sha(raw)))
        return receipt["id"]


def strict_scene_json(value):
    # Scene bounds/digest stay defined by the existing model; duplicate fields
    # and nonfinite values are refused before validate() or receipt interpretation.
    if not isinstance(value, str):
        raise LinkError("Stored scene/test JSON must be text")
    raw = value.encode("utf-8")
    if len(raw) > 600_000:
        raise LinkError("Stored scene/test JSON exceeds its bound")
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise LinkError("Duplicate stored scene/test field")
            result[key] = item
        return result
    def constant(_):
        raise LinkError("Nonfinite stored scene/test value")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "withdraw", "undo", "receipt"):
        action = sub.add_parser(command)
        action.add_argument("request", type=Path)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("link_id")
    args = parser.parse_args(argv)
    try:
        ledger = ParameterLinks(args.project)
        if args.command == "inspect":
            result = ledger.inspect(args.link_id)
        else:
            request = strict_json(pdf._read(args.request, MAX_JSON_BYTES))
            if args.command == "create":
                result = ledger.create(request)
            elif args.command == "withdraw":
                _keys(request, ("link_id", "review"))
                result = ledger.withdraw(request["link_id"], request["review"])
            elif args.command == "undo":
                _keys(request, ("event_id", "review"))
                result = ledger.undo(request["event_id"], request["review"])
            else:
                _keys(request, ("link_id", "receipt"))
                result = ledger.attach_test_receipt(request["link_id"], request["receipt"])
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (LinkError, pdf.PDFEvidenceError, OSError, ValueError, TypeError, KeyError,
            sqlite3.Error, OverflowError, RecursionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
