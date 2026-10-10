"""Explicit local metadata exports; never sends private PDFs/images or executes."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import tempfile

from core import pdf_evidence as pdf
from core.research_bundle import export_bundle, BundleError
from workspace3d.parameter_links import ParameterLinks

LINK_SCHEMA = "ideaforge.reviewed-parameter-link.v1"
PHOTO_SCHEMA = "ideaforge.reviewed-photo-inventory.v1"


@contextmanager
def _input_summary(root, result):
    """Stage owned JSON temporarily; its hash is not the original PDF hash."""
    from core.research_bundle import _root, _checked_file, _signature
    raw = (json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")) + "\n").encode("utf-8")
    if not 1 <= len(raw) <= 262144:
        raise BundleError("Selected result summary exceeds 256 KiB")
    folder = root
    for component in ("research", "result_inputs"):
        folder = pdf._path(root, str(folder.relative_to(root) / component))
        if not folder.exists():
            folder.mkdir()
        _root(folder)  # Reject every existing symlink/junction/reparse ancestor.
    path = None
    initial = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix="bundle_input_", suffix=".json",
                                         delete=False) as handle:
            path = type(root)(handle.name)
            handle.write(raw)
            handle.flush()
        relative = path.relative_to(root).as_posix()
        checked, initial = _checked_file(root, relative)
        yield {"id": "reviewed_input", "path": relative,
               "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
               "media_type": "application/json"}
    finally:
        if path is not None and path.exists():
            checked, current = _checked_file(root, path.relative_to(root).as_posix())
            if initial is not None and _signature(current) != _signature(initial):
                raise BundleError("Owned staging file changed; cleanup refused")
            checked.unlink()


def export_reviewed_result(project_root, directory_name, *, schema, result,
                           producer_revision, tests, test_only=False):
    """Local export of an explicitly selected app-owned result summary.

    The caller supplies truthful passed/failed/unrun declarations. This function
    performs no test execution, data transmission or automatic Aster adoption.
    Binary PDF/image inputs are deliberately not accepted.
    """
    root, project_id, _ = pdf._identity(project_root)
    if schema not in (LINK_SCHEMA, PHOTO_SCHEMA):
        raise BundleError("Unsupported IdeaForge result schema")
    if not isinstance(result, dict) or result.get("project_id") != project_id:
        raise BundleError("Selected result belongs to a different project")
    revision = result.get("revision")
    if not isinstance(revision, str):
        raise BundleError("Result requires an explicit revision string")
    if schema == PHOTO_SCHEMA and (result.get("original_image_bytes_in_bundle") is not False
                                  or result.get("image_verification") != "unavailable"):
        raise BundleError("Original images are not included or verified by this bundle")
    if not isinstance(tests, list) or not tests:
        raise BundleError("At least one honest test declaration is required")
    declarations = []
    for test in tests:
        if not isinstance(test, dict) or set(test) != {"id", "status", "details"}:
            raise BundleError("Test declaration requires only id/status/details")
        declarations.append({**test, "artifact_ids": ["reviewed_result"],
                             "input_ids": ["reviewed_input"]})
    # Use the canonical shared producer's strict bounds/path/type checks before
    # touching local summary storage, including app-owned opaque result bounds.
    from core.research_bundle import _bounded, _text, _path, _root, _array, _id
    _root(root)
    if type(test_only) is not bool:
        raise BundleError("test_only must be an explicit boolean")
    if len(_path(directory_name)) != 1 or (root / directory_name).exists():
        raise BundleError("Choose a fresh portable export directory name")
    _bounded(result)
    _text(project_id, 128, "project_id")
    _text(revision, 128, "revision")
    _text(result.get("status"), 128, "status")
    _text(producer_revision, 128, "producer_revision")
    _array(declarations, 32, "tests")
    for test in declarations:
        _id(test["id"], "test.id")
        _text(test["details"], 4096, "test.details", multiline=True)
        if test["status"] not in ("passed", "failed", "unrun"):
            raise BundleError("Invalid test status")
    with _input_summary(root, result) as selected_input:
        return export_bundle(root, directory_name, app_id="ideaforge", project_id=project_id,
                             revision=revision,
                             results=[{"id": "reviewed_result", "schema": schema,
                                       "status": result["status"], "result": result}],
                             inputs=[selected_input], tests=declarations,
                             provenance={"origin": "Explicit local user-reviewed result metadata",
                                         "producer_revision": producer_revision,
                                         "model": "none; no model execution by exporter",
                                         "test_only": test_only})


def export_parameter_link(project_root, link_id, directory_name, *, producer_revision, test_only=False):
    """Prepare selected reviewed quote/parameter metadata from a local ledger.

    Full native passage, private filename, root binding, reviewer and review
    rationale are excluded. The selected numeric quote, page/box and preserved
    source SHA remain source claims; Aster can verify included JSON bytes only.
    """
    ledger = ParameterLinks(project_root)
    item = ledger.inspect(link_id)
    record = item["record"]
    source = record["source"]
    result = {
        "project_id": record["project_id"], "revision": record["revision"],
        "status": item["status"], "link_id": record["id"],
        "link_record_sha256": item["record_sha256"], "scene_hash": record["scene_hash"],
        "parameter": record["parameter"], "parameter_value": record["parameter_value"],
        "parameter_unit": record["parameter_unit"],
        "source": {key: source[key] for key in ("source_id", "version_id", "citation",
                   "source_sha256", "page", "bbox", "object_index", "coordinate_system")},
        "selected_quote": record["selection"], "reasons": item["reasons"],
        "original_pdf_bytes_in_bundle": False, "pdf_source_verification": "unavailable",
        "review_identity_verification": "operator_assertion_only",
        "dimension_validation": "unavailable",
    }
    tests = []
    for number, entry in enumerate(item["tests"], 1):
        receipt = entry["receipt"]
        receipt_raw = json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
        tests.append({"id": "link_receipt_" + str(number), "status": receipt["status"],
                      "details": ("Previously reviewed local receipt SHA256 " +
                          hashlib.sha256(receipt_raw).hexdigest() + ". Evidence status: " +
                          entry["evidence_status"] +
                          ". Exporter did not independently run this test; original command "
                          "and private observations remain in the local ledger.")})
    if not tests:
        tests = [{"id": "link_evidence_unrun", "status": "unrun",
                  "details": "No reviewed link-bound test receipt exists. Exporter ran no tests."}]
    if len(tests) > 32:
        raise BundleError("Link has more than 32 receipts; explicitly select a bounded export")
    return export_reviewed_result(project_root, directory_name, schema=LINK_SCHEMA,
                                  result=result, producer_revision=producer_revision, tests=tests, test_only=test_only)
