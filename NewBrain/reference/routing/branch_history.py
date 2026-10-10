"""Append experimental reports above the entire immutable 220 history.

No file IO or execution at import. Original ownership/report text is preserved.
Root wrappers/process/IO remain independently authenticated external records;
history bytes are audit ancestry and never neural input or retrieval features.
"""
import hashlib
import struct
import history_archive as parent_history

MAGIC = b'NBMH228\x00'
HEADER = struct.Struct('<8sII')
ITEM = struct.Struct('<II')
PARENT_CAP, REPORT_CAP, HISTORY_CAP = 2752512, 2097152, 12582912
NEW_KEYS = ('228/migration','228/before-method','228/method-train','228/blind-post','228/reopen')
ROLE_REPORT_BOUNDS = dict(zip(NEW_KEYS, (2097152, 1459200, 1606656, 1557504, 1557504)))
HISTORY_UPPER = HEADER.size+PARENT_CAP+sum(ITEM.size+len(k)+ROLE_REPORT_BOUNDS[k] for k in NEW_KEYS)


def need(ok, why):
    if not ok: raise RuntimeError(why)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def original(raw, expected_hash):
    need(type(raw) is bytes and 0 < len(raw) <= PARENT_CAP and sha(raw) == expected_hash,
        'Whole exact accepted parent220 history')
    parts = parent_history.unpack(raw)
    need(len(parts[2]) == 8 and len(parts[3]) == 4 and
        tuple(k for k, _ in parts[3]) == parent_history.NEW_KEYS,
        'All eight earlier and four complete220 reports')
    return parts


def pack(parent_raw, entries):
    need(type(parent_raw) is bytes and 0 < len(parent_raw) <= PARENT_CAP and
        type(entries) is list and 1 <= len(entries) <= len(NEW_KEYS),
        'Complete parent and finite ordered branch reports')
    parent_parts = parent_history.unpack(parent_raw)
    need(len(parent_parts[2]) == 8 and len(parent_parts[3]) == 4,
        'Only the complete accepted parent history is a branch start')
    parts = [HEADER.pack(MAGIC, len(parent_raw), len(entries)), parent_raw]
    for (name, raw), key in zip(entries, NEW_KEYS):
        need(name == key and type(raw) is bytes and 0 < len(raw) <= ROLE_REPORT_BOUNDS[key],
            'Exact full next branch report')
        encoded = name.encode('ascii')
        parts.extend((ITEM.pack(len(encoded), len(raw)), encoded, raw))
    result = b''.join(parts)
    need(len(result) <= HISTORY_UPPER < HISTORY_CAP and
        result[HEADER.size:HEADER.size+len(parent_raw)] == parent_raw,
        'Whole immutable parent history embedded once')
    return result


def unpack(raw):
    need(type(raw) is bytes and HEADER.size <= len(raw) <= HISTORY_UPPER,
        'Whole selected experimental history frame')
    magic, size, count = HEADER.unpack(raw[:HEADER.size])
    need(magic == MAGIC and 0 < size <= PARENT_CAP and 1 <= count <= len(NEW_KEYS) and
        HEADER.size+size <= len(raw), 'Exact finite frame before allocation')
    at = HEADER.size; parent_raw = raw[at:at+size]; at += size
    parent_parts = parent_history.unpack(parent_raw)
    need(len(parent_parts[2]) == 8 and len(parent_parts[3]) == 4, 'Every complete parent report')
    entries, spans = [], []
    for key in NEW_KEYS[:count]:
        need(at+ITEM.size <= len(raw), 'Full new report header')
        kn, n = ITEM.unpack(raw[at:at+ITEM.size]); at += ITEM.size
        need(kn == len(key) and 0 < n <= ROLE_REPORT_BOUNDS[key] and at+kn+n <= len(raw) and
            raw[at:at+kn] == key.encode('ascii'), 'Exact order/extent before full report slice')
        at += kn; spans.append((key, at, n)); entries.append((key, raw[at:at+n])); at += n
    need(at == len(raw) and pack(parent_raw, entries) == raw, 'Entire old/new byte roundtrip')
    return parent_raw, parent_parts, entries, spans


def append(parent_raw, entries, role, report, previous_raw=None):
    need(type(entries) is list and len(entries) < len(NEW_KEYS) and
        '228/'+role == NEW_KEYS[len(entries)], 'One actual next branch role')
    result = pack(parent_raw, entries+[('228/'+role, report)])
    if previous_raw is not None:
        prior, _, prior_entries, _ = unpack(previous_raw)
        need(prior == parent_raw and prior_entries == entries, 'Every complete prior branch report preserved')
        need(result[HEADER.size:len(previous_raw)] == previous_raw[HEADER.size:],
            'Only outer count changes; full prior payload remains an exact byte prefix')
    return result
