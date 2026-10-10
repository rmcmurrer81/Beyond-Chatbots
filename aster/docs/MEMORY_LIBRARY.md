# Private memory and local reference library

These two support modules provide owner-local records and real, deterministic
substring retrieval. They do not provide NewBrain recall, learning, generated
answers, embeddings, semantic ranking, or an alternate cognition backend.
No accounts, credentials, package installs, network requests, or external
services are used. NewBrain's existing unavailable state is unchanged.

## Private memory

`PrivateMemory(store)` extends the existing `memories` records with a companion
metadata table. It does not replace the owner's identity, change memory IDs,
rewrite old bodies, or alter the original five-column memory table. Records
written by the original `Store.remember` remain readable and searchable with
category `history` and state `active` until explicitly changed.

The supported categories are `decision`, `preference`, and `history`. Each
record retains its original creation timestamp, source text and supersession
link. Optional `source_date` is an ISO calendar date or timezone-qualified ISO
timestamp supplied by the caller. It is a claimed source date, not a verified
file creation date. The creation timestamp `at` remains a Unix timestamp.

Public methods:

- `status()` reports implemented capability and retention limitations.
- `remember(body, category='history', source='user', supersedes=None, source_date=None)`
  appends a record and returns its ID.
- `search(query='', category=None, source=None, include_hidden=False,
  include_deleted=False, include_superseded=False, limit=50)` returns newest-first
  records. All options except `query` are keyword-only. The query is a literal,
  Unicode case-insensitive substring of the body; `%`, `_` and quotes are ordinary
  characters. Category and source filters are exact. Empty query lists records.
- `get(id_)` explicitly inspects an individual retained record, in any state.
- `correct(id_, body, category=None, source=None, source_date=None)` appends a new
  record linked to the existing one; options are keyword-only. Source and
  category inherit unless overridden. The correction's optional source date
  does not inherit. Only an active current record can be corrected, preventing
  accidental branches. Original Store-created branches can still be inspected.
- `chain(id_)` returns the retained correction family from its root, including
  hidden/deleted members and legacy branches. Cycles or families beyond 1,000
  records fail explicitly rather than looping or silently truncating.
- `hide(id_)`, `delete(id_)`, `restore(id_)` change the visibility of exactly one
  record and return that record. Repeated identical controls are idempotent.

### Deletion and correction are explicit

**Delete means recoverably hidden, not erased.** It stores `state='deleted'`;
body, provenance, IDs and correction links remain in SQLite and may also exist
in its journal/backups. `retained_data: true` is returned. There is no purge or
secure-erasure API, and this database is not encrypted.

Ordinary search excludes hidden, deleted and superseded records. A corrected
record remains superseded even if its replacement is hidden or deleted, so
old claims are never silently promoted to current truth. Restore acts on one
record, not an entire family; restoring an old correction does not make it the
current record.

The low-level `Store.rows('memories')` remains retained administrative history.
Calling it directly will show bodies regardless of visibility state. User-facing
ordinary memory/history projections must use the filtered module API; an
explicit retained-history view can reveal them with a clear retention label.
No caller should label these controls permanent deletion.

Bodies and source strings retain the existing Store size limits (32 KiB and
1 KiB UTF-8 respectively). Search accepts at most 1 KiB of query text and 1–100
results. Memory content is not duplicated in audit-event payloads.

## Approved local reference library

`ReferenceLibrary(store, files=None)` uses the same hardened `Files` adapter as
workspace reads. Pass the existing adapter when integrating it into an active
session. It must belong to the same Store. If omitted, the library creates and
owns an adapter; call `close()` when finished. A caller-supplied adapter remains
the caller's responsibility.

The library reads only explicit files under separately approved workspace
folders. It never searches the owner's home, crawls directories, discovers
external libraries, follows a link, or treats an imported document's text as
permission. It does not modify source files.

Public methods:

- `status()` reports supported formats, bounds and unconfigured adapters.
- `approve_folder(relative_folder)` securely validates an existing real folder
  under `<state>/workspace`, stores its approval, and returns its folder record
  including `id`. For example, approve `references/project-a`. A deliberate
  `'.'` approval authorizes the workspace root, but is never added implicitly.
  Approval itself does not index any files.
- `folders()` lists approvals, including revoked ones.
- `index_files(folder_id, paths)` accepts an explicit list of 1–32
  workspace-relative filenames (for example `references/project-a/manual.txt`).
  It reads and validates the entire batch before committing snapshots. Files
  must lie below the approved folder. No recursive or glob scan is supported.
  The result contains source IDs, path, SHA-256, byte count and indexing time.
- `sources(folder_id=None)` lists active-scope source metadata with live freshness
  checks, without returning source text.
- `search(query, folder_id=None, limit=20)` returns exact cached text passages
  with path, 1-based line/column ranges, snapshot SHA-256, source ID, indexing time
  and live freshness. Options are keyword-only. Results are path-ordered,
  then source-ID-ordered, then passage-ordered, with a maximum of 100.
- `revoke_folder(folder_id)` disables all reads, searches and source listings
  through that approval immediately. It returns `cached_bytes_retained: true`.

Example using an existing Store and Files:

```python
from aster.private_memory import PrivateMemory
from aster.reference_library import ReferenceLibrary

memory = PrivateMemory(store)
original = memory.remember('Use metric units', category='decision', source='owner')
correction = memory.correct(original, 'Use millimetres for drawings', source='owner')
assert memory.search('millimetres')[0]['id'] == correction

library = ReferenceLibrary(store, files)
folder = library.approve_folder('references/project-a')
library.index_files(folder['id'], ['references/project-a/manual.txt'])
hits = library.search('torque')
library.revoke_folder(folder['id'])
assert library.search('torque') == []
```

### Scope, limits and stale citations

Supported inputs are `.txt`, `.md`, and `.json` files containing strict UTF-8
text. JSON is treated as quoted source text; it is not executed or interpreted
as commands. Unsupported formats, invalid UTF-8, NUL/ASCII/C1 control-byte
content, nonregular files, multiple hard links, and files above 256 KiB are
rejected. Tab, CR and LF are permitted. The complete cache is limited to 128
sources and 8 MiB of source bytes, with at most 32 retained approval records.
All of these count retained revoked-scope data too. There is no hidden pruning
or eviction to make room. Existing Store database bounds still apply.

Search is a literal, Unicode case-insensitive substring of source body text,
not of filenames. The query must be nonempty, single-line and at most 512 UTF-8
bytes. No FTS expression syntax or semantic similarity is implied. At most one
match per source line is returned; adjacent matching context windows may
overlap. A passage contains the matching line and up to two neighboring lines
on either side, capped at 4,096 characters. Very long lines yield a clipped
excerpt with exact character columns. Line numbering recognizes LF, CRLF and
CR; column numbers count Unicode source characters and include retained line
terminators where an entire line is returned. The full-file hash is SHA-256 of
the original bytes, including BOM or original line endings.

Each hit is a cached snapshot, explicitly labelled `snapshot: true`. A safe
live read is performed to classify the source:

- `fresh`: current safe file bytes equal the cached source hash; `stale=false`.
- `changed`: readable current bytes have a different hash; `stale=true`.
- `missing`: source no longer exists; `stale=true`.
- `unavailable`: safe reading is refused or fails; `stale=true`.

Cached quotations from stale sources remain inspectable under an active
approval, with their original hash and a clear stale flag. They must never be
presented as quotations from the new live version. Only explicit reindexing
refreshes the snapshot; reindexing preserves the source ID and updates its
hash and indexing date. Source file creation/modification timestamps are not
claimed. Freshness describes the observed read, not a guarantee against a
later change.

Revocation is per approval. An independently approved overlapping folder is a
separate grant and must also be revoked to disable that path completely.
Revoked cached bodies remain in local SQLite; no secure-erasure claim is made.
Explicitly approving the same folder again preserves its approval ID and makes
its retained cache eligible for results, with current freshness checks.

POSIX reads use anchored directory descriptors and no-follow opens. Windows
reads use the existing fail-closed local fixed-NTFS adapter, retaining native
ancestor handles and rejecting reparse points, junctions, ADS/device paths,
short-name aliases and unsupported case-sensitive directories. Path spelling
is canonicalized with the platform adapter. No unsafe fallback is added.
The existing trusted-owner state-directory boundary is unchanged; this is not
a sandbox against hostile processes under the same OS account or administrators.

PDF parsing, OCR, Zotero, external folders, automatic discovery and semantic
retrieval are explicitly **unconfigured**, not silently emulated. No NewBrain
prompt, document content, model output or external text may invoke an approval
or control method without a separate owner action in the integrating interface.

## Verification

Focused tests cover migration compatibility, identity and record persistence,
literal/Unicode lookup, provenance, correction families, recoverable visibility,
atomic rollback, socket-denied operation, explicit approval and revocation,
path confinement, symlink/hardlink/FIFO refusal on POSIX, exact source hashes and
line/column citations, live stale detection, cache bounds and restart behavior.
Evidence with commands, UTC timestamps, environment versions, source hashes,
results, skips and any corrected failures is retained under
`test-results/2026-10-05-support-modules/memory-*` and `library-*`.
Native Windows runtime coverage must be obtained on Windows; grammar checks or
Linux skips are not substitutes for a native adapter test run.
