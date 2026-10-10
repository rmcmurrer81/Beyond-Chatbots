# Communications Desk and Media / Voice Workshop

These are usable owner-local vertical slices, implemented with the Python standard
library. They are not account connectors, AI assistants, or a complete media studio.
No account authentication, network request, provider mutation, message sending,
model/runtime download, subprocess, automatic playback, TTS, avatar generation,
Zotero integration, or video editor is activated by either module.

## Communications Desk

`Communications(store, files)` imports owner-prepared UTF-8 JSON exports from the
managed Aster workspace. It uses **one exact common schema**, not guessed Gmail,
Outlook, ICS, GitHub API, MBOX, or other provider formats:

```json
{
  "schema_version": 1,
  "service": "email",
  "account": "owner@example.test",
  "exported_at": "2026-10-05T10:00:00Z",
  "records": [
    {
      "id": "owner-selected-record-1",
      "source": "email:owner-selected-export/record-1",
      "date": "2026-10-04T12:30:00+02:00",
      "title": "Exact exported subject or title",
      "body": "Exact owner-selected source text."
    }
  ]
}
```

- `service` is exactly `email`, `calendar`, or `github`. Each export has one service
  and account. Account identity and provider/source assertions are declared by the
  exporter, not authenticated by Aster.
- `date` is the original record timestamp chosen by the exporter. Calendar start,
  end, attendees, recurrence and GitHub state can be retained in the body as text;
  there is no scheduling, recurrence interpretation or issue-state synchronization.
- Dates require valid RFC3339 date/time with explicit timezone, optionally with
  1–6 fractional-second digits. Their spelling and offsets are retained exactly.
- Exactly the listed fields are required. Extra/missing fields, duplicate JSON
  keys, duplicate record IDs within an export, unsupported versions, nonfinite
  numbers, invalid UTF-8/Unicode, and forbidden controls fail closed.
- Maximum file size is 256 KiB, with 100 records per export. Text byte limits:
  account 320, record ID 128, source 2,048, title 512, body 16,384. The body may
  be empty and may contain newline/tab/carriage return. Other text must be nonempty.
- Source links are inert strings. Imported text is untrusted data, never commands,
  prompts to execute, automatically fetched URLs, or verified model claims.

### APIs and deliberate actions

1. `preview_import(path)` reads and validates without importing. Its `sha256` is
   the hash of the exact file bytes, with account/service/source/date/title summary.
2. Show that preview to the user. `import_export(path,
   expected_sha256=preview['sha256'], approved=True)` performs the deliberate local
   import. `approved` must be the actual boolean `True`. Changed bytes require a
   fresh preview. Approval does not grant any account or sending access.
3. `search(query='', service=None, account=None, limit=50, offset=0)` returns a local
   inbox. Search is Unicode-casefolded literal substring matching over record
   ID/source/date/title/body. `%`, `_` and SQL text are ordinary text. Service/account
   filters are exact. Limits are 1–100, offsets 0–1,000,000. Newest imports/records
   appear first; dates are retained as provenance, not reinterpreted for ordering.
4. `read(snapshot_id, record_id)` opens one exact immutable snapshot record.
5. `create_draft(service, account, recipient, subject, body, approved=True)` saves
   only exact user-written text. It generates no claims, replies, addresses or
   commitments. Account and recipient strings are unverified local labels.
6. `outbox(limit=50, offset=0)` lists current drafts, always `UNSENT` with
   `sending_enabled: false`. `draft(id)` reads an exact revision. Deliberate
   `revise_draft(id, recipient, subject, body, approved=True)` appends a revision
   and keeps the original. Stale revisions cannot be edited into a second branch.

Exports and drafts are persisted in module-owned SQLite tables with append-only
triggers and content digests. Reads verify payload integrity. Exact duplicate export
bytes are idempotent even after a repeated click. Different export bytes remain
separate snapshots, including conflicting versions of the same source record.
There is no deletion/retention UI, no de-duplication across changed snapshots, and no
live synchronization. Caller UI must escape all source and user text as plain text.

## Media / Voice Workshop

`MediaWorkshop(store, files)` provides `inspect(path)`, `preview_trim(path,
start_frame, end_frame, output_path)`, `trim(...)`, `inspect_voice()`, and `status()`.

### PCM WAV scope

- Inputs must already be in the managed workspace and have a `.wav` suffix.
- The 256 KiB Files bound applies. Classic little-endian RIFF/WAVE integer PCM,
  mono/stereo, 8/16/24/32-bit, 8,000–192,000 Hz is supported. Float, compressed,
  extensible-format, RF64, MP3 and video inputs are rejected.
- Exactly one 16-byte PCM format chunk and one complete nonempty data chunk are
  required. Format rates/alignment/data lengths are checked against each other and
  Python's `wave` parser. Truncation, trailing bytes and duplicate chunks are rejected.
  Like Python's writer, a final odd-byte data chunk may omit its pad byte.
- Inspection reports exact channels, sample width/rate, byte count, frame count,
  file SHA-256, PCM SHA-256, duration as seconds, and exact `frames/sample_rate`
  fraction. It does not play audio or assess listening quality.
- Trim uses integer sample-frame indices `[start_frame, end_frame)`, with
  `0 <= start < end <= frames`. Stereo frames contain both channels; selected PCM
  bytes are copied exactly, without mixing, resampling, effects or model generation.
- The output must be a separate file under `media/exports/` with `.wav` suffix.
  Casefold-equal input/output paths are rejected conservatively on all platforms.
  Input files and original supplied voice assets remain unchanged.
- Ancillary input chunks are deliberately omitted from the output copy. The result
  contains a fresh classic PCM WAV header and exactly the selected PCM samples.

### Preview receipt, write and recovery

`preview_trim('media/source.wav', 0, 8000, 'media/exports/first-second.wav')`
returns a nonmutating plan. Its `sha256` is the **plan receipt**, not the source
file hash. It binds source path/hash, start/end frames, destination path, exact
previous destination hash (or null for absence), and generated output hash. Review
`previous_output_sha256` carefully: an existing destination will be replaced, with
its previous bytes retained by Files.

Only `trim(path, start_frame, end_frame, output_path,
expected_sha256=preview['sha256'], approved=True)` writes. Any change detected during revalidation of source,
frame selection, output path or previous output bytes invalidates the receipt.
The returned `change_id` is the existing Files journal operation. Use
`files.undo(change_id)` to restore previous output or remove a newly created copy.
An external edit detected at undo revalidation blocks undo rather than overwriting it. Interrupted
writes remain prepared and must be reconciled with `files.recover()` before retry.

Files retains its existing owner-controlled workspace, no-follow/link restrictions,
single writer and platform security behavior. This is not a sandbox against a
hostile same-user process changing files concurrently; it does not claim atomic
source/destination compare-and-swap against adversarial external edits.

### Supplied voice provenance

`inspect_voice()` directly reuses `aster.voice.inspect_voice()`, including all five
pinned file hashes and WAV signal/metadata checks. It neither copies nor modifies
the original 691,244-byte audition, which deliberately exceeds this workshop's
256 KiB generic workspace input bound. Its result remains a prerecorded audition,
not live synthesis, an AI response, owner likeness, or NewBrain output. Manual
playback remains separately controlled. Listening review was not performed here.

## VideoStudio source review and reuse decision

A separate external-source review informed the decision to keep this increment
small. Its private repository metadata and detailed source-review receipt are
not included in Aster publication. No VideoStudio source was copied or executed.
This module directly reuses Aster's own scoped Files journal and integrity-checked
voice inspector. Video export, soundtrack processing, generative voice and avatars
remain future adapters with separately reviewed runtime, dependency and license
requirements. No external source audit or upstream test pass is claimed by the
published Aster test results.

## Verification

Focused test receipts/logs live under
`test-results/2026-10-05-support-modules/communications-*` and `media-*`.
Each real test run records UTC, command, interpreter/platform, source hashes,
pass/fail and skipped tests through `scripts/record_support_check.py`. Deterministic
synthetic PCM fixtures exercise actual WAV bytes, not listening quality or TTS.
The supplied pack test verifies real original voice hashes before and after use.

Linux/POSIX focused tests do not qualify native Windows, external account access,
GUI delivery, provider sending, VideoStudio runtimes or listening quality. No such
claim follows from these tests.

### Concurrent-editor boundary

Do not concurrently edit selected input or output files while a trim or undo is running. Hash checks detect changes at revalidation time, but the existing Files journal is not an atomic compare-and-swap against arbitrary concurrent writers. A save between the final check and replacement can still be overwritten; the trusted, owner-controlled workspace assumption remains. Undo rejects a differing file when checked; this is not protection against a writer racing after that check.
