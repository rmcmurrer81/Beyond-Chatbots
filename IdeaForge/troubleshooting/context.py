"""Exact, bounded context policy for troubleshooting.

No directory traversal, free-form research summaries, PDF/photo/OCR stores,
private staging, conversation logs, or incidental filenames enter this context.
The named metadata files below are intentional provider inputs. A user-supplied
problem or explicitly attached image is a separate, explicit input.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MAX_SOURCE_BYTES = 65536
MAX_LOCAL_CHARS = 12000
MAX_PROJECT_CHARS = 3500
MAX_FIELD_CHARS = 600
MAX_ITEMS = 12


def contained_path(root, relative):
    """Reject traversal and every linked component below the canonical root."""
    root = Path(root).resolve(strict=True)
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Project paths must be relative and contained.")
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved != path:
        raise ValueError("Linked or outside-project troubleshooting path.")
    return path


def read_json(root, relative, default=None, limit=MAX_SOURCE_BYTES):
    path = contained_path(root, relative)
    try:
        with path.open("rb") as stream:
            if os.fstat(stream.fileno()).st_nlink != 1:
                raise ValueError("Linked troubleshooting source.")
            raw = stream.read(limit + 1)
    except FileNotFoundError:
        return default
    if len(raw) > limit:
        raise ValueError("Troubleshooting source exceeds its byte budget.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Troubleshooting metadata must be a JSON object.")
    return value


def _text(value, limit=MAX_FIELD_CHARS):
    # Do not stringify nested metadata, arbitrary objects, or filenames.
    return value.encode("utf-8")[:limit].decode("utf-8", "ignore") if isinstance(value, str) else None


def _strings(value):
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value[:MAX_ITEMS]
            if isinstance(item, str)]


def project_context(root):
    value = read_json(root, "project.json", {})
    identity = value.get("project_id")
    if identity is None:
        identity = "legacy-" + hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]
    if not isinstance(identity, str) or not identity or len(identity) > 128 or any(ord(c) < 32 for c in identity):
        raise ValueError("Invalid troubleshooting project identity.")
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    out = {"project_id": identity, "name": _text(value.get("name"), 200),
           "summary": _text(plan.get("summary")),
           "capabilities": _strings(plan.get("capabilities")),
           "subsystems": _strings(plan.get("subsystems")),
           "unknowns": _strings(plan.get("unknowns"))}
    # Keep valid JSON and deterministic priority rather than cutting JSON text.
    for key in ("capabilities", "subsystems", "unknowns"):
        while len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > MAX_PROJECT_CHARS and out[key]:
            out[key].pop()
    return out


def _memory(value):
    # Raw source_text, extraction payloads and superseded revisions stay local.
    current = {}
    facts = value.get("facts", [])
    if not isinstance(facts, list):
        return {"status": "unavailable"}
    # Reject pathological counts instead of silently selecting an old prefix.
    if len(facts) > 256:
        return {"status": "over budget"}
    for item in facts:
        if not isinstance(item, dict):
            continue
        key = _text(item.get("key"), 100)
        if key and not item.get("superseded_by") and item.get("status") != "superseded":
            current[key] = item
    selected = []
    for key in sorted(current)[:MAX_ITEMS]:
        item = current[key]
        # Only explicitly saved user facts qualify; unknown/imported sources
        # cannot implicitly promote PDF/photo/OCR passages to provider context.
        if item.get("source") != "user_statement":
            continue
        selected.append({field: _text(item.get(field), limit) for field, limit in
                         (("key", 100), ("statement", 500), ("unit", 50), ("category", 50))})
    return {"current_user_facts": selected}


def local_context(root, max_chars):
    budget = max(0, min(int(max_chars), MAX_LOCAL_CHARS))
    if not budget:
        return ""
    chunks = []
    # This is the complete allowlist. Adding a source requires a policy review.
    for relative, project in (("project.json", True), ("project_memory.json", False)):
        try:
            value = project_context(root) if project else _memory(read_json(root, relative, {}))
        except (OSError, ValueError, TypeError):
            value = {"status": "unavailable; no source contents included"}
        chunk = relative + ": " + json.dumps(value, ensure_ascii=False)
        if len("\n\n".join(chunks + [chunk]).encode("utf-8")) <= budget:
            chunks.append(chunk)
    return "\n\n".join(chunks)
