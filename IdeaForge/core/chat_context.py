"""Bounded project state and local, citation-bearing evidence for ordinary chat.

JSON files remain authoritative. The per-project SQLite FTS5 index is a disposable
cache, refreshed transactionally from allowlisted source files before retrieval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from inventory.equipment import load_all

MAX_CONTEXT_CHARS = 18000
MAX_SOURCE_BYTES = 4_000_000
MAX_PASSAGES = 6
PASSAGE_CHARS = 900
MAX_INDEX_PASSAGES = 1000
MAX_URL_CHARS = 2048


def _read(root, relative, default):
    """Do not follow a project source symlink into a different project."""
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Source outside project: {relative}")
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError(f"Source exceeds size limit: {relative}")
        if not relative.endswith('.json'):
            return raw.decode('utf-8')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f'Expected JSON object: {relative}')
        return value
    except FileNotFoundError:
        return default


def project_id(root):
    root = Path(root)
    project = _read(root, 'project.json', {})
    # Legacy projects have no ID; their folder identity must never use the title.
    identity = str(project.get('project_id') or 'legacy-' + hashlib.sha256(
        str(root.resolve()).encode()).hexdigest()[:24])
    if len(identity) > 128 or any(ord(char) < 32 for char in identity):
        raise ValueError('Invalid project ID')
    return identity


def _bounded(value, limit):
    """Keep JSON valid; disclose truncation instead of cutting a serialized object."""
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) <= limit:
        return value
    if isinstance(value, list):
        kept = []
        for item in value:
            candidate = kept + [item]
            if len(json.dumps(candidate, ensure_ascii=False)) > limit - 100:
                continue
            kept = candidate
        return {'items': kept, 'omitted_count': len(value) - len(kept)}
    return {'excerpt': encoded[:max(0, limit - 100)], 'truncated': True}


def current_snapshot(root):
    root = Path(root)
    project = _read(root, 'project.json', {})
    memory = _read(root, 'project_memory.json', {})
    # Last stored revision wins for legacy duplicate keys; normal writes upsert.
    facts = {}
    stored = memory.get('facts', [])
    if not isinstance(stored, list):
        raise ValueError('Expected facts list')
    for fact in stored:
        if not isinstance(fact, dict):
            continue
        key = fact.get('key')
        if not isinstance(key, str):
            continue
        if key and not fact.get('superseded_by') and fact.get('status') != 'superseded':
            facts[key] = fact
    current = sorted(facts.values(), key=lambda x: str(x.get('updated_at', '')), reverse=True)
    # Raw user turns remain on disk for audit; do not repeat them for every fact.
    fields = {'key': 100, 'statement': 600, 'value': 150, 'unit': 50,
              'category': 50, 'updated_at': 80}
    current = [{key: _bounded(fact.get(key), limit) for key, limit in fields.items()}
               for fact in current]
    plan = project.get('plan') or {}
    if not isinstance(plan, dict):
        raise ValueError('Expected project plan object')
    try:
        loaded = load_all()
        inventory = loaded.get('items', []) if isinstance(loaded, dict) else []
        if not isinstance(inventory, list):
            raise ValueError('Expected inventory list')
        # Inventory is intentionally shared, but project-tagged entries are scoped.
        inventory = [x for x in inventory if isinstance(x, dict)
                     and x.get('project_id') in (None, project_id(root))]
    except (OSError, ValueError, TypeError):
        inventory = {'status': 'unavailable; equipment specifications remain TBD'}
    return {
        'project_id': project_id(root),
        'name': _bounded(project.get('name'), 300),
        'saved_user_facts': _bounded(current, 4500),
        'fact_provenance': 'Model-extracted user statements, not independently verified measurements. Latest stored key supersedes older values.',
        'selected_reference': _bounded(_read(root, 'design/selected_reference.json', None), 1600),
        'owned_equipment_shared_inventory': _bounded(inventory, 2000),
        'generated_plan_open_questions': _bounded(plan.get('research_questions', []), 2000),
        'generated_plan_unknowns': _bounded(plan.get('unknowns', []), 1000),
        'missing_values': 'Missing, null, omitted, or TBD values are unknown; never infer engineering values.',
    }


def _source_url(value):
    value = str(value or '')
    if len(value) > MAX_URL_CHARS or any(ord(char) < 32 for char in value):
        return ''
    parsed = urlsplit(value)
    return value if parsed.scheme in ('https', 'http') and parsed.netloc and parsed.username is None else ''


def _documents(root):
    bundle = _read(root, 'research/research.json', {})
    for bucket in ('web', 'papers'):
        items = bundle.get(bucket, []) or []
        if not isinstance(items, list):
            raise ValueError(f'Expected research {bucket} list')
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            text = str(item.get('snippet') or item.get('summary') or item.get('title') or '')
            yield (f'research/research.json#/{bucket}/{i}', str(item.get('title') or '')[:300],
                   _source_url(item.get('url') or item.get('doi')), 'untrusted_source_excerpt', text)
    # These are AI-written synthesis, never primary evidence.
    for relative in ('research/RESEARCH_BRIEF.md', 'research/LATEST_DISCOVERIES.md'):
        text = _read(root, relative, '')
        if text:
            yield relative, relative, '', 'generated_summary_not_primary_evidence', text


def _connect(root):
    path = Path(root) / 'chat_evidence.sqlite3'
    if path.is_symlink():
        raise ValueError('Evidence database must not be a symlink')
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS evidence USING fts5('
                   'project_id UNINDEXED, citation UNINDEXED, locator UNINDEXED, '
                   'url UNINDEXED, kind UNINDEXED, title, passage)')
    except Exception:
        db.close()
        raise
    return db


def refresh_index(root):
    """Replacement removes stale/deleted source passages; never indexes old facts."""
    root = Path(root)
    identity = project_id(root)
    rows = []
    truncated = False
    for locator, title, url, kind, text in _documents(root):
        for offset in range(0, len(text), PASSAGE_CHARS):
            if len(rows) >= MAX_INDEX_PASSAGES:
                truncated = True
                break
            passage = text[offset:offset + PASSAGE_CHARS]
            location = f'{locator}@{offset}:{offset + len(passage)}'
            digest = hashlib.sha256(json.dumps(
                [identity, location, title, url, kind, passage], ensure_ascii=False
            ).encode()).hexdigest()[:24]
            rows.append((identity, 'IF-' + digest, location, url, kind, title[:300], passage))
        if truncated:
            break
    db = _connect(root)
    try:
        with db:
            # The database belongs to one project, even if a folder was copied.
            db.execute('DELETE FROM evidence')
            db.executemany('INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    finally:
        db.close()
    return truncated


def literal_query(text):
    """FTS operators, quotes, SQL, and punctuation cannot become query syntax."""
    words = list(dict.fromkeys(re.findall(r'\w+', str(text)[:2000], re.UNICODE)))[:24]
    return ' OR '.join('"' + word.replace('"', '""') + '"' for word in words)


def retrieve(root, query, limit=MAX_PASSAGES):
    expression = literal_query(query)
    if not expression:
        return []
    db = _connect(root)
    try:
        rows = db.execute(
            'SELECT project_id, citation, locator, url, kind, title, passage FROM evidence '
            'WHERE evidence MATCH ? AND project_id = ? ORDER BY rank, citation LIMIT ?',
            (expression, project_id(root), max(0, min(int(limit), MAX_PASSAGES))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def resolve_citation(root, citation):
    """Return a cached exact excerpt and source locator, scoped to this project ID."""
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM evidence WHERE project_id = ? AND citation = ?',
                         (project_id(root), citation.strip('[]'))).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def build_context(root, query):
    snapshot = current_snapshot(root)
    try:
        truncated = refresh_index(root)
        evidence = retrieve(root, query)
        status = 'Local saved excerpts only; no live source verification.'
        if truncated:
            status += ' Source coverage incomplete: index passage budget reached.'
    except (OSError, ValueError, sqlite3.Error):
        evidence = []
        status = 'Evidence unavailable (source/index unreadable or SQLite FTS5 unavailable); do not invent citations.'
    payload = {'current_project_state': snapshot, 'retrieval_status': status, 'evidence': evidence}
    encoded = json.dumps(payload, ensure_ascii=False)
    # Defensive cap: evidence never crowds out current project state.
    while len(encoded) > MAX_CONTEXT_CHARS and evidence:
        evidence.pop()
        payload['retrieval_status'] = status + ' Some excerpts omitted for context budget.'
        encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_CONTEXT_CHARS:
        # Defensive last resort for unusual escape-heavy or malformed metadata.
        return json.dumps({'project_id': snapshot['project_id'], 'context_status':
                           'Project context exceeded budget; facts and evidence omitted. Values remain unknown.'})
    return encoded
