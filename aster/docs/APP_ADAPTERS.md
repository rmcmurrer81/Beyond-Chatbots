# Owner-selected research export capabilities

This milestone is an Aster-side, deterministic local data reader. It does not
connect to, launch, import or command IdeaForge or Humanoid Researcher. App
registration discovery remains separate and registration-only; see [APPS.md](APPS.md).
The existing research catalog authorizes its two app recipients, not Aster.
This module never reads its research records, impersonates either app, changes
grants, or follows a registered installation path.

Public bridge source inspected in the local IdeaForge/Humanoid checkouts exposes
registration, project-specific research sharing and recipient context retrieval.
That source does not establish an installed Aster command API. In particular,
unpublished work in another checkout is not an installed or approved capability.
Live app commands and code execution remain disabled. NewBrain remains absent.

## Explicit local scope

`AppAdapters(store, files)` uses only the existing platform-safe `Files.read`
boundary. Both the manifest and research export must already be below
`<state>/workspace`, individually named with workspace-relative paths. Aster
does not collect exports from another application's directories. The owner
prepares/reviews the data separately and puts the selected export into Aster's
workspace. No source URL is opened or fetched.

The owner previews a file, then approves its exact SHA-256. Registration snapshots
the strict manifest; selection snapshots the export for one exact app/project.
Later changes to either source file cannot silently change the approved snapshot.
This is local approval of already-selected bytes, not an external app permission,
proof of origin, or a persistent grant to another application's data.

The registry, selection and disable histories are append-only. They use Aster's
existing state database without replacing identity, prompts or memories. All data
remains under the same trusted-owner storage assumptions and 64 MiB database cap
as the rest of Aster. The workspace reader's 256 KiB per-file limit also applies.
The journal contains export contents, including after deselection or disable;
these actions do not erase data. Do not put credentials into exports.

## Manifest version 1

Every field below is required; additional fields are rejected. Only exact integer
schema/adapter version 1 is accepted. Known origin IDs are `ideaforge` and
`humanoid-researcher`. There is no import path, executable, endpoint, shell command,
wildcard project or open-ended permission field.

```json
{
  "schema_version": 1,
  "adapter_version": 1,
  "adapter_kind": "workspace_research_export",
  "app_id": "ideaforge",
  "recipient": "aster",
  "capabilities": ["research.inspect", "research.read"],
  "projects": [{"id": "project-a", "label": "Owner-selected project"}]
}
```

Declare 1–20 distinct, exact project IDs. `capabilities` is a nonempty unique subset
of the two operations shown. Unsupported operations or versions cannot be
registered. Missing, unregistered, disabled, incompatible or integrity-mismatched
capabilities cannot read research. Labels and origin declarations are
owner-supplied metadata, never evidence that an app is installed or running.

## Export version 1

This is an Aster-owned interchange contract, not a claim that either app currently
produces this format. Every field is required and extra fields are rejected.

```json
{
  "schema_version": 1,
  "app_id": "ideaforge",
  "project_id": "project-a",
  "recipient": "aster",
  "records": [{
    "id": "source-record-1",
    "source": "https://example.org/paper",
    "title": "Research reference",
    "excerpt": "Unverified source excerpt.",
    "model": "source excerpt; not model-generated",
    "claim_key": "claim-a",
    "supersedes": null
  }]
}
```

An export has 0–100 distinct records. IDs/project IDs are at most 128 UTF-8 bytes,
source references 2,048 bytes, titles 240, excerpts 4,096, model/claim labels 160.
Control characters are rejected except newlines, carriage returns and tabs inside
excerpts. Duplicate JSON fields, malformed UTF-8/JSON and nonfinite numbers are
rejected. The selected app, project and Aster recipient must match exactly.

Source/model declarations and original record IDs are retained without pretending
they are authenticated. Conflicting and superseded records remain separate;
supersession is stored as a reference only and never updates canonical data.
Research text is always inert data. The reader does not generate an answer,
interpret instructions, evaluate code, import modules, launch processes, make
network calls or transfer data to an AI backend.

## Python interface for CLI/controller integration

```python
exports = AppAdapters(store, files)
preview = exports.preview_manifest("exports/manifest.json")
registered = exports.register("exports/manifest.json",
    expected_sha256=preview["sha256"], approved=True)

preview = exports.preview_export(registered["id"], "project-a", "exports/research.json")
selection = exports.select(registered["id"], "project-a", "exports/research.json",
    expected_sha256=preview["sha256"], approved=True)

exports.inspect()  # Metadata and source provenance, without excerpts.
exports.read(record_id="source-record-1")  # Exact record in the selected snapshot.
exports.read()  # All records in that bounded snapshot.
```

The caller must obtain the owner's explicit approval before setting `approved=True`.
Preview is not approval. Preview output includes SHA-256 and metadata, not the
research body; the owner can review the already-selected workspace file with
Aster's existing file reader. Digest binding ensures those exact bytes are chosen.

- `status()` returns local `selection`, newest 100 manifest metadata records,
  total/truncation indicators and explicit disabled live/AI/execution flags.
- `list()` returns newest 100 manifest metadata records, no research bodies.
- `preview_manifest(path)` returns validated `manifest`, `sha256`, path and size.
- `register(path, *, expected_sha256, approved=False)` returns manifest metadata
  with its immutable `id`. This enrolls an owner-selected export capability only.
- `preview_export(manifest_id, project_id, path)` returns export digest, record
  count and scope, without creating a selection or exposing excerpts.
- `select(manifest_id, project_id, path, *, expected_sha256, approved=False)`
  returns `selection_id`, exact app/project, digest and local snapshot status.
- `selected()` returns that metadata or `None`; it never reads the source file.
- `inspect(selection_id=None)` requires `research.inspect`; returns provenance
  records without excerpts. An omitted ID uses the current explicit selection.
- `read(selection_id=None, record_id=None)` requires `research.read`; returns the
  bounded snapshot's records, or one exact record when requested.
- `clear_selection()` removes only the default selection. Earlier approved
  snapshots remain accessible by exact ID, and their history is retained.
- `disable(manifest_id, approved=False)` disables new and historical reads under
  that manifest. It is idempotent and preserves history. Re-enrollment requires a
  new exact owner approval and creates a separate immutable manifest ID.

Successful reads/inspections and mutations record minimal events, without copying
research bodies into event payloads. A file changing between preview and approval
is rejected. There is no automatic retry, watching, resync, catalog fallback,
capability discovery by imports, or runtime/plugin loader.

## Validation

`python -m unittest discover -s tests -p test_app_adapters.py -v` covers strict
schemas, exact approval hashes, app/project separation, capability restrictions,
snapshot persistence, revocation, history, preservation of Aster identity/memory,
inert research text, and the workspace file boundary. POSIX link fixtures run on
POSIX; Windows uses the existing native `Files` implementation and its separate
native test suite. A Linux run is not a claim of new Windows validation.
