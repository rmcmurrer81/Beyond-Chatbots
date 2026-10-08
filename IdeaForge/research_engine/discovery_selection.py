"""Bounded, source-balanced discovery candidates with durable version identity.

The ledger is project-local. Model scores prioritize review; they are not truth
probabilities. Provider recency order is never presented as relevance evidence.
"""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

BUCKETS = ('papers', 'web', 'images')
MAX_CANDIDATES = 40
MAX_RECORDS = 5000
LEASE_SECONDS = 600
CATEGORIES = ('buildable_now', 'experimental', 'enabling_research', 'reference', 'not_useful')
TEXT_FIELDS = ('why_useful', 'what_it_changes', 'recommended_next_step')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return ''
    try:
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return ''
        port = p.port
    except ValueError:
        return ''
    host = p.hostname.lower()
    if ':' in host: host = '[' + host + ']'
    if port and (p.scheme, port) not in (('http', 80), ('https', 443)):
        host += ':' + str(port)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('gclid', 'fbclid')]
    return urlunsplit((p.scheme.lower(), host, p.path or '/', urlencode(query), ''))


def evidence(item, bucket):
    """Canonical IDs never merge merely because two papers have the same title."""
    if not isinstance(item, dict): return None
    title = str(item.get('title') or '')[:300]
    url = safe_url(item.get('image_url') if bucket == 'images' else item.get('url'))
    doi = str(item.get('doi') or '').strip()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'https://dx.doi.org/', 'doi:'):
        if doi.lower().startswith(prefix): doi = doi[len(prefix):]
    if not doi and urlsplit(url).hostname in ('doi.org', 'dx.doi.org'):
        doi = urlsplit(url).path.lstrip('/')
    doi = doi.casefold() if doi.startswith('10.') and '/' in doi and not any(c.isspace() for c in doi) else ''
    if not url and doi: url = safe_url('https://doi.org/' + doi)
    if not url: return None  # A title alone is not an actionable source.
    identity = 'doi:' + doi if doi and bucket != 'images' else 'url:' + url
    source_id = digest(identity)
    # Exclude mutable ranking/count metadata and tracking parameters from identity.
    body = {k: str(item.get(k) or '')[:12000] for k in ('snippet', 'summary', 'date', 'published')}
    version = digest({'title': title, 'body': body, 'url': url if not doi else identity})
    return {'_id': 'IFD-' + source_id[:20] + '-' + version[:20],
            'source_id': source_id, 'source_version': version, '_bucket': bucket,
            'title': title, 'url': url, 'source': str(item.get('source') or '')[:80],
            'snippet': (body['snippet'] or body['summary'])[:800],
            'date': (body['date'] or body['published'])[:80],
            '_query': str(item.get('_query') or '')[:300]}


def normalized(bundle):
    rows = {}
    for bucket in BUCKETS:
        items = (bundle or {}).get(bucket, []) or []
        if not isinstance(items, list): raise ValueError('Expected source list')
        if len(items) > MAX_RECORDS: raise ValueError('Discovery source batch exceeds limit')
        for item in items:
            row = evidence(item, bucket)
            if row is not None: rows.setdefault(row['_id'], row)
    return list(rows.values())


def balanced(rows, limit=MAX_CANDIDATES):
    """Round-robin source coverage; oldest pending records keep later work fair."""
    groups = {key: {} for key in BUCKETS}
    for row in rows:
        groups[row['_bucket']].setdefault(row.get('_query', ''), []).append(row)
    out = []
    selected_sources=set()
    while len(out) < limit and any(groups.values()):
        for key in BUCKETS:
            if groups[key] and len(out) < limit:
                query = next(iter(groups[key]))
                queue = groups[key].pop(query)
                row=queue.pop(0)
                if row['source_id'] not in selected_sources:
                    out.append(row);selected_sources.add(row['source_id'])
                if queue: groups[key][query] = queue
    return out


@contextmanager
def connect(root):
    root = Path(root).resolve()
    directory = root / 'research'
    directory.mkdir(exist_ok=True)
    if not directory.resolve().is_relative_to(root): raise ValueError('Discovery path outside project')
    path = directory / 'discovery_ledger.sqlite3'
    if path.is_symlink(): raise ValueError('Discovery ledger must not be a symlink')
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, data TEXT NOT NULL, '
               'state TEXT NOT NULL, lease TEXT, expires REAL, created REAL NOT NULL, bucket TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()


def claim(root, before, after, now=None):
    now = time.time() if now is None else now
    new = normalized(after)
    old = normalized(before)
    token = uuid.uuid4().hex
    with connect(root) as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
            for row in old:
                db.execute('INSERT OR IGNORE INTO candidates VALUES (?,?,?,NULL,NULL,?,?)',
                           (row['_id'], json.dumps(row), 'baseline', now, row['_bucket']))
            db.execute("INSERT INTO metadata VALUES ('initialized','1')")
        for row in new:
            db.execute('INSERT OR IGNORE INTO candidates VALUES (?,?,?,NULL,NULL,?,?)',
                       (row['_id'], json.dumps(row), 'pending', now, row['_bucket']))
        pending = []
        for bucket in BUCKETS:
            pending.extend(db.execute("SELECT data FROM candidates WHERE bucket=? AND (state='pending' OR "
                "(state='leased' AND expires<=?)) ORDER BY created,rowid LIMIT ?",
                (bucket, now, MAX_RECORDS)).fetchall())
        selected = balanced([json.loads(x['data']) for x in pending])
        for row in selected:
            db.execute("UPDATE candidates SET state='leased',lease=?,expires=? WHERE id=?",
                       (token, now + LEASE_SECONDS, row['_id']))
    return token, selected


def release(root, token):
    with connect(root) as db:
        db.execute("UPDATE candidates SET state='pending',lease=NULL,expires=NULL WHERE lease=? AND state='leased'", (token,))


def validate_output(value, candidates):
    if not isinstance(value, dict) or set(value) != {'discoveries'}:
        raise ValueError('Invalid discovery response object')
    rows = value['discoveries']
    if not isinstance(rows, list) or len(rows) > len(candidates):
        raise ValueError('Invalid discovery response list')
    known = {row['_id']: row for row in candidates}
    seen = set()
    validated = []
    keys = {'item_id', 'usefulness_score', 'category', *TEXT_FIELDS}
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('Invalid discovery response fields')
        identity = row['item_id']
        if not isinstance(identity, str) or identity not in known or identity in seen:
            raise ValueError('Unknown or repeated evidence ID')
        seen.add(identity)
        score = row['usefulness_score']
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid discovery score')
        if row['category'] not in CATEGORIES: raise ValueError('Invalid discovery category')
        if any(not isinstance(row[k], str) or len(row[k]) > 1600 for k in TEXT_FIELDS):
            raise ValueError('Invalid discovery explanation')
        original = known[identity]
        validated.append(dict(row, title=original['title'], url=original['url'],
                              source_id=original['source_id'], source_version=original['source_version'],
                              evidence_excerpt=original['snippet'], evidence_kind='retrieved_source_claim',
                              assessment_label='Model usefulness judgment; not a verified engineering conclusion'))
    return validated


def complete(root, token, candidates, useful, now=None):
    now = time.time() if now is None else now
    with connect(root) as db:
        db.execute('BEGIN IMMEDIATE')
        owned = {r['id'] for r in db.execute("SELECT id FROM candidates WHERE lease=? AND state='leased' AND expires>?", (token, now))}
        if owned != {r['_id'] for r in candidates}: raise ValueError('Discovery lease expired or changed')
        if useful:
            record = {'id': token, 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)), 'discoveries': useful}
            db.execute('INSERT INTO reports VALUES (?,?,?)', (token, json.dumps(record, ensure_ascii=False, allow_nan=False), now))
        db.execute("UPDATE candidates SET state='done',lease=NULL,expires=NULL WHERE lease=?", (token,))
    return useful


def schema(candidates):
    properties = {'item_id': {'type': 'string', 'enum': [r['_id'] for r in candidates]},
                  'usefulness_score': {'type': 'number', 'minimum': 0, 'maximum': 1},
                  'category': {'type': 'string', 'enum': list(CATEGORIES)}}
    properties.update({k: {'type': 'string', 'maxLength': 1600} for k in TEXT_FIELDS})
    return {'type': 'object', 'additionalProperties': False, 'required': ['discoveries'],
            'properties': {'discoveries': {'type': 'array', 'maxItems': len(candidates),
                'items': {'type': 'object', 'additionalProperties': False,
                          'required': list(properties), 'properties': properties}}}}
