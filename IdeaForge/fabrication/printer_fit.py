"""Project-selected reviewed printer bounding-box screening, using only the stdlib.

Coordinates and dimensions are explicit millimetres. Results are geometric bounds
only: no slicer, support, process, material or printability assessment.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
from core.pdf_evidence import _path as _owned_path, PDFEvidenceError
from pathlib import Path
from contextlib import contextmanager

PROFILE_FORMAT = "ideaforge.printer-profile.v1"
RECEIPT_FORMAT = "ideaforge.printer-fit.v1"
ORIENTATIONS = ("xyz", "xzy", "yxz", "yzx", "zxy", "zyx")
MAX_BYTES = 131072
MAX_KEEP_OUTS = 32
MAX_COORD = 1000000
MAX_DB_BYTES = 32 * 1024 * 1024
LIMITATIONS = [
    "Geometric bounding-box screening only; six axis permutations at the declared placement.",
    "No automatic rotation, placement, printer selection, CAD dimension validation or design adoption.",
    "No supports, toolpath, material, adhesion, process, deformation or printability validation.",
    "Keep-out contact fails conservatively; box clearance does not establish exact mesh clearance.",
]


class FitInputError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value, name, maximum=256):
    if (not isinstance(value, str) or not value.strip() or
            len(value.encode("utf-8")) > maximum or
            any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)):
        raise FitInputError(name + " must be bounded nonempty text without controls.")
    return value


def _vector(value, name, *, positive=False):
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(x) not in (int, float) or not 0 <= x <= MAX_COORD or
                not math.isfinite(x) or (positive and x <= 0) for x in value)):
        raise FitInputError(name + " requires three finite bounded " +
                            ("positive" if positive else "nonnegative") + " numbers, never booleans.")
    return list(value)


def _bounded(value):
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise FitInputError("Input must be finite bounded JSON.") from error
    if len(encoded) > MAX_BYTES:
        raise FitInputError("Input exceeds the 128 KiB limit.")


def validate_profile(profile):
    required = {"format", "units", "usable_xyz", "margins_min_xyz",
                "margins_max_xyz", "keep_outs", "review"}
    if not isinstance(profile, dict) or set(profile) != required:
        raise FitInputError("A complete reviewed printer profile is required; unknown fields are rejected.")
    _bounded(profile)
    if profile["format"] != PROFILE_FORMAT or profile["units"] != "mm":
        raise FitInputError("Reviewed profile must use format v1 and explicit units mm.")
    usable = _vector(profile["usable_xyz"], "usable_xyz", positive=True)
    low = _vector(profile["margins_min_xyz"], "margins_min_xyz")
    high = _vector(profile["margins_max_xyz"], "margins_max_xyz")
    if any(low[i] + high[i] >= usable[i] for i in range(3)):
        raise FitInputError("Margins leave no positive usable extent.")
    review = profile["review"]
    if not isinstance(review, dict) or set(review) != {"reviewer", "note"}:
        raise FitInputError("Explicit reviewer and review note are required.")
    _text(review["reviewer"], "reviewer", 128)
    _text(review["note"], "review note", 2048)
    keep = profile["keep_outs"]
    if not isinstance(keep, list) or len(keep) > MAX_KEEP_OUTS:
        raise FitInputError("At most 32 rectangular keep-outs are supported.")
    ids = set()
    for box in keep:
        if not isinstance(box, dict) or set(box) != {"id", "min_xyz", "max_xyz"}:
            raise FitInputError("Keep-out requires only id, min_xyz and max_xyz.")
        bid = box["id"]
        if not isinstance(bid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bid) or bid in ids:
            raise FitInputError("Keep-out IDs must be unique portable identifiers.")
        ids.add(bid)
        minimum = _vector(box["min_xyz"], "keep-out minimum")
        maximum = _vector(box["max_xyz"], "keep-out maximum")
        if any(not minimum[i] < maximum[i] <= usable[i] for i in range(3)):
            raise FitInputError("Keep-outs must have positive extent inside usable XYZ.")
    return copy.deepcopy(profile)


def _unknown(reason):
    return {"status": "unknown", "geometric_fit": None, "reason": str(reason),
            "declared_orientation": None, "configurations": [],
            "limitations": list(LIMITATIONS)}


def screen_geometry(model, profile):
    """Screen six permutations; never chooses a permutation or infers missing units."""
    try:
        if not isinstance(model, dict) or set(model) != {"units", "size_xyz", "placement"}:
            raise FitInputError("Explicit model units, size_xyz and placement are required.")
        _bounded(model)
        if model["units"] != "mm":
            raise FitInputError("Model units are missing or unsupported; explicit mm is required.")
        size = _vector(model["size_xyz"], "size_xyz", positive=True)
        placement = model["placement"]
        if not isinstance(placement, dict) or set(placement) != {"units", "min_xyz", "orientation"}:
            raise FitInputError("Declared placement requires units, min_xyz and orientation.")
        if placement["units"] != "mm" or placement["orientation"] not in ORIENTATIONS:
            raise FitInputError("Placement requires explicit mm and one of the six orientations.")
        minimum = _vector(placement["min_xyz"], "placement minimum")
        profile = validate_profile(profile)
    except (FitInputError, TypeError, ValueError, RecursionError) as error:
        return _unknown(error)
    lower = profile["margins_min_xyz"]
    upper = [profile["usable_xyz"][i] - profile["margins_max_xyz"][i] for i in range(3)]
    configurations = []
    for orientation in ORIENTATIONS:
        extent = [size["xyz".index(axis)] for axis in orientation]
        maximum = [minimum[i] + extent[i] for i in range(3)]
        contained = all(lower[i] <= minimum[i] and maximum[i] <= upper[i] for i in range(3))
        hits = [box["id"] for box in profile["keep_outs"]
                if all(min(maximum[i], box["max_xyz"][i]) >=
                       max(minimum[i], box["min_xyz"][i]) for i in range(3))]
        configurations.append({"orientation": orientation, "size_xyz_mm": extent,
                               "min_xyz_mm": list(minimum), "max_xyz_mm": maximum,
                               "inside_effective_bounds": contained,
                               "keep_out_hits": hits, "geometric_fit": contained and not hits})
    chosen = next(x for x in configurations if x["orientation"] == placement["orientation"])
    return {"status": "fit" if chosen["geometric_fit"] else "not_fit",
            "geometric_fit": chosen["geometric_fit"], "reason": None,
            "declared_orientation": placement["orientation"],
            "effective_min_xyz_mm": list(lower), "effective_max_xyz_mm": upper,
            "configurations": configurations, "limitations": list(LIMITATIONS)}


def strict_json(raw):
    if type(raw) is str:
        raw=raw.encode("utf-8",errors="strict")
    if type(raw) is not bytes or len(raw)>MAX_BYTES:
        raise FitInputError("Expected bounded UTF-8 JSON.")
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise FitInputError("Duplicate JSON key.")
            result[key]=value
        return result
    def bad_constant(value):
        raise FitInputError("Nonfinite JSON value: "+value)
    try:
        value=json.loads(raw.decode("utf-8",errors="strict"),object_pairs_hook=unique,
                         parse_constant=bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise FitInputError("Invalid bounded UTF-8 JSON.") from error
    _bounded(value)
    return value


def _read_json(path):
    with Path(path).open("rb") as handle:
        raw=handle.read(MAX_BYTES+1)
    return strict_json(raw)


def same_json(left,right):
    """Canonical JSON equality preserves boolean/integer distinctions."""
    try:
        return digest(left)==digest(right)
    except (TypeError, ValueError, RecursionError):
        return False


def _local_path(root, relative, *, directory=False, maximum=MAX_DB_BYTES):
    root=Path(root).absolute()
    try:
        path=_owned_path(root,relative)
    except PDFEvidenceError as error:
        raise FitInputError(str(error)) from error
    cursor=path
    while True:
        try: info=cursor.lstat()
        except FileNotFoundError: info=None
        if info is not None:
            if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
                raise FitInputError("Project paths must not use symlinks or reparse points.")
            if cursor==path:
                if directory:
                    if not stat.S_ISDIR(info.st_mode):
                        raise FitInputError("Expected a local project directory.")
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>maximum:
                    raise FitInputError("Project file must be bounded, regular and have one hard link.")
        if cursor==root: break
        cursor=cursor.parent
    return path


def history_path(root):
    for suffix in ("","-journal","-wal","-shm"):
        _local_path(root,"workspace3d/history.sqlite3"+suffix)
    return _local_path(root,"workspace3d/history.sqlite3")


def _inventory_items(inventory):
    if inventory is None:
        from inventory.equipment import load_all
        inventory = load_all(strict_ids=True)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("items"), list):
        raise FitInputError("Inventory items are unavailable.")
    return inventory["items"]


def _printer(inventory, printer_id):
    matches = [x for x in _inventory_items(inventory) if isinstance(x, dict) and
               x.get("equipment_id") == printer_id]
    if len(matches) != 1 or matches[0].get("category") != "3d_printer":
        raise FitInputError("Selected printer ID must match exactly one 3d_printer inventory item.")
    _bounded(matches[0])
    return copy.deepcopy(matches[0])


class PrinterFitStore:
    """Append-only project selection revisions and immutable geometric receipts."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.path = self.root / "workspace3d" / "history.sqlite3"
        self.root_sha256 = digest(os.path.normcase(str(self.root.resolve())))

    def _project(self):
        _local_path(self.root,"",directory=True)
        if digest(os.path.normcase(str(self.root.resolve())))!=self.root_sha256:
            raise FitInputError("Canonical project root changed.")
        project = _read_json(_local_path(self.root,"project.json",maximum=MAX_BYTES))
        if not isinstance(project, dict):
            raise FitInputError("Project identity is unavailable.")
        _text(project.get("project_id"), "project_id", 128)
        return project["project_id"], digest(project)

    @contextmanager
    def _connect(self, *, initialize=True):
        identity=self._project()
        _local_path(self.root,"workspace3d",directory=True).mkdir(parents=True,exist_ok=True)
        history_path(self.root)
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS printer_selections (
                        project_id TEXT NOT NULL, root_sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
                        record TEXT NOT NULL, PRIMARY KEY(project_id,root_sha256,revision));
                    CREATE TABLE IF NOT EXISTS printer_receipts (
                        sha256 TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                        root_sha256 TEXT NOT NULL, receipt TEXT NOT NULL);
                """)
            with db:
                yield db
                history_path(self.root)
                if self._project()!=identity:
                    raise FitInputError("Project identity or revision changed during the operation.")
        finally:
            db.close()

    def selection(self):
        project_id, _ = self._project()
        if not self.path.exists():
            return None
        with self._connect(initialize=False) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='printer_selections'").fetchone():
                return None
            row = db.execute("SELECT record,revision FROM printer_selections WHERE project_id=? AND root_sha256=? "
                             "ORDER BY revision DESC LIMIT 1", (project_id,self.root_sha256)).fetchone()
        if row:
            value = strict_json(row["record"])
            if (not isinstance(value, dict) or set(value) !=
                    {"project_id","root_sha256","revision","printer_id","printer_sha256","profile_sha256","profile"} or
                    value["project_id"] != project_id or value["root_sha256"] != self.root_sha256 or type(value["revision"]) is not int or value["revision"] < 1 or type(row["revision"]) is not int or value["revision"] != row["revision"]):
                raise FitInputError("Stored printer selection is malformed.")
            _text(value["printer_id"], "printer_id", 128)
            for name in ("printer_sha256","profile_sha256"):
                if not isinstance(value[name],str) or not re.fullmatch(r"[0-9a-f]{64}",value[name]):
                    raise FitInputError("Stored printer selection hash is malformed.")
            profile=validate_profile(value["profile"])
            if digest(profile)!=value["profile_sha256"]:
                raise FitInputError("Stored profile hash is inconsistent.")
            return value
        return None

    def select(self, printer_id, profile, *, expected_revision, inventory=None, expected_project_revision=None):
        identity=self._project()
        project_id,project_revision=identity
        if expected_project_revision is not None and expected_project_revision!=project_revision:
            raise FitInputError("Project changed since profile review opened.")
        _text(printer_id, "printer_id", 128)
        profile = validate_profile(profile)
        item = _printer(inventory, printer_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise FitInputError("Expected selection revision must be a nonnegative integer.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._project()!=identity or digest(_printer(inventory,printer_id))!=digest(item):
                raise FitInputError("Project or printer changed before selection approval.")
            row = db.execute("SELECT MAX(revision) FROM printer_selections WHERE project_id=? AND root_sha256=?",
                             (project_id,self.root_sha256)).fetchone()
            current = row[0] or 0
            if type(current) is not int or current < 0:
                raise FitInputError("Stored selection revision is invalid.")
            if current != expected_revision:
                raise FitInputError("Printer selection changed; reload before saving.")
            record = {"project_id": project_id, "root_sha256":self.root_sha256, "revision": current + 1,
                      "printer_id": printer_id, "printer_sha256": digest(item),
                      "profile_sha256": digest(profile), "profile": profile}
            db.execute("INSERT INTO printer_selections VALUES (?,?,?,?)",
                       (project_id, self.root_sha256, current + 1, json.dumps(record, allow_nan=False)))
            if self._project()!=identity or digest(_printer(inventory,printer_id))!=digest(item):
                raise FitInputError("Project or printer changed during selection approval.")
        return record

    def screen(self, model, *, model_revision, inventory=None):
        binding = {"root_sha256":self.root_sha256, "project_id": None, "project_revision": None, "model_revision": None,
                   "model_sha256": None, "selection_revision": None,
                   "selected_printer_id": None, "printer_sha256": None, "profile_sha256": None}
        try:
            project_id, project_revision = self._project()
            binding.update(project_id=project_id, project_revision=project_revision)
            _text(model_revision, "model_revision", 128)
            _bounded(model)
            binding.update(model_revision=model_revision, model_sha256=digest(model))
            selection = self.selection()
            if not selection:
                raise FitInputError("No project-selected reviewed printer profile.")
            binding.update(selection_revision=selection["revision"],
                           selected_printer_id=selection["printer_id"],
                           printer_sha256=selection["printer_sha256"],
                           profile_sha256=selection["profile_sha256"])
            item = _printer(inventory, selection["printer_id"])
            if digest(item) != selection["printer_sha256"]:
                raise FitInputError("Selected inventory printer changed; re-review the profile.")
            profile = validate_profile(selection["profile"])
            if digest(profile) != selection["profile_sha256"]:
                raise FitInputError("Reviewed printer profile hash is inconsistent.")
            result = screen_geometry(model, profile)
        except (OSError, sqlite3.Error, FitInputError, KeyError, TypeError, ValueError, RecursionError) as error:
            result = _unknown(error)
        return {"format": RECEIPT_FORMAT, "binding": binding, "result": result}

    def current(self, receipt, model, *, model_revision, inventory=None):
        """Recompute against current inputs; a stored success is never trusted."""
        try:
            _bounded(receipt)
            return same_json(receipt,self.screen(model, model_revision=model_revision, inventory=inventory))
        except (OSError, ValueError, TypeError):
            return False

    def save_receipt(self, receipt, model, *, model_revision, inventory=None):
        fingerprint = digest(receipt)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.current(receipt, model, model_revision=model_revision, inventory=inventory):
                raise FitInputError("Stale or altered printer-fit receipt; rerun screening.")
            project_id, _ = self._project()
            db.execute("INSERT OR IGNORE INTO printer_receipts VALUES (?,?,?,?)",
                       (fingerprint, project_id, self.root_sha256, json.dumps(receipt, allow_nan=False)))
        return fingerprint

    def receipt(self, fingerprint, *, model=None, model_revision=None, inventory=None):
        if not isinstance(fingerprint,str) or not re.fullmatch(r"[0-9a-f]{64}",fingerprint):
            raise FitInputError("Receipt hash must be lowercase SHA-256.")
        project_id, _ = self._project()
        if not self.path.exists():
            return None
        with self._connect(initialize=False) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='printer_receipts'").fetchone():
                return None
            row = db.execute("SELECT receipt FROM printer_receipts WHERE sha256=? AND project_id=? AND root_sha256=?",
                             (fingerprint, project_id,self.root_sha256)).fetchone()
        if not row:
            return None
        value=strict_json(row[0])
        if digest(value)!=fingerprint:
            raise FitInputError("Stored receipt bytes do not match its requested hash.")
        if not self.current(value,model,model_revision=model_revision,inventory=inventory):
            value["result"]=_unknown("Stored receipt lacks current model inputs or is stale/altered; rerun screening.")
            value["stale"]=True
        return value


def part_model(part):
    return {"units": "mm", "size_xyz": copy.deepcopy(part.get("size_mm")),
            "placement": copy.deepcopy(part.get("printer_placement"))}


def scene_receipts(scene, root=None, *, inventory=None):
    revision = digest(scene)
    store = PrinterFitStore(root) if root is not None else None
    return [{"part": part["id"],
             "receipt": store.screen(part_model(part), model_revision=revision, inventory=inventory)
             if store else {"format": RECEIPT_FORMAT, "binding": None,
                            "result": _unknown("Project scope and reviewed printer selection are required.")}}
            for part in scene["parts"]]

def stale_receipts(scene):
    return [{"part":part["id"], "axis_aligned_fit":None,
             "receipt":{"format":RECEIPT_FORMAT, "binding":None,
                        "result":_unknown("Stored printer-fit receipt is stale or altered; run current checks.")}}
            for part in scene["parts"]]
