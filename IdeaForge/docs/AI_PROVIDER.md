# Text provider selection: preparation only

IdeaForge continues to default to **Standalone**. Its existing local Ollama text
model and settings remain in `ai/config.json`. A separate, explicit **Aster**
selection is now prepared, but **Aster has no qualified live app-provider backend
or transport in this change**. Choosing it reports unavailable. It cannot generate
answers, connect to Aster's private memory, or silently use another model.

## Select and inspect

From the IdeaForge repository directory, using the application's Python runtime:

```sh
python -m ai.provider
python -m ai.provider --provider aster
python -m ai.provider --provider standalone
```

These commands only read or atomically update the repository's `ai_provider.json`.
They do not install software, invoke a model, start a listener, configure an
endpoint, create credentials, or grant persistent access. The GUI's AI label
shows the current selection. It updates when the file changes. The Standalone
label identifies the configured model; it does not claim that Ollama is reachable.
The Aster label explicitly says unavailable and vision disabled.

The exact app-wide selection shape is:

```json
{
  "protocol": "aster.provider.selection.v1",
  "provider": "standalone",
  "app_id": "ideaforge",
  "revision": 1
}
```

A missing selection file defaults to Standalone. Invalid, cross-app, or unknown
configuration fails explicitly instead of falling back. A project ID is never
saved in this app-wide file. Operations bind the selected provider to the current
project in memory. CLI changes increment the revision.

## Operation and failure rules

- Each chat turn, direct model operation, and queued background pass captures the
  provider selection and revision, complete AI configuration digest, canonical
  project path and ID, process session ID, unique operation/request IDs, an absolute
  deadline, and cancellation state. Nested extraction, equipment enrichment,
  troubleshooting query generation, and all background synthesis stages reuse
  this capture. The new-project definition starts in workspace scope, then an
  explicit child-project binding retains the same captured provider/revision.
- Text calls preserve the app's messages, prompts, JSON mode or discovery JSON
  schema, temperature, token limit, and raw response text. Parsing, retrieval,
  source identities, discovery validation, deterministic CAD/simulation, and
  safety/evidence checks remain app-owned. A routing receipt is not a claim of
  engineering validity.
- Messages are bounded to 64 records, 65,536 UTF-8 bytes per message, and 180,000
  bytes for the serialized message list. Responses are bounded to 262,144 UTF-8
  bytes. Oversized contexts fail explicitly; the adapter does not cut JSON or
  silently omit project records. Existing app context builders retain their own
  smaller bounds.
- Chat/direct operations use the captured configured timeout (at most 30 minutes)
  as an overall deadline; background queues receive a 30-minute absolute deadline
  at enqueue time. Standalone HTTP timeouts are capped by remaining time. These
  synchronous HTTP calls are not forcibly interrupted mid-socket-read; deadline
  and cancellation checks discard late results before app publication.
- Changing provider/configuration or project identity during a call invalidates
  its completion. Starting a newer chat turn or closing the UI cancels the old
  turn. Closing the app cancels queued/active background operations. A provider
  failure never triggers an alternative model.
- Each successful routing return adds an in-memory provenance receipt to the
  active operation: app/project/session/request, task/schema, selected provider,
  selection revision/digest, AI config digest and operation ID. The chat exposes
  its last operation's receipts in `last_provider_provenance`. These are diagnostic
  routing records, not persisted transcripts, replay instructions, or validation
  receipts. Standalone and offline test output are labeled distinctly.
- Provider-unavailable, unsupported, cancelled, deadline and stale errors are
  propagated past optional-stage exception handlers. Background failures appear
  as errors/interrupted operations, never as research completion. Downloaded
  research remains saved. New evidence is registered as pending before synthesis
  on update passes; failed discovery assessments release their own leases.
- Requests are not replayed after restart. Previously queued/running research is
  marked interrupted before watch threads start, and must be explicitly resumed
  with Research. Completed/idle projects retain normal watch scheduling; a new
  due watch is a new operation with a fresh capture. Deterministic workspace jobs
  and evidence ledgers retain their existing app-owned persistence.

## Coverage and separate capabilities

All 13 text call sites are routed: chat/project definition; project memory;
equipment extraction and enrichment; research horizon, summary, discovery
assessment, reference variants and virtual-build concepts; prototype planning;
simulation planning; troubleshooting queries and diagnosis.

The `qwen3-vl:8b` image analyzer remains an explicit **Standalone vision specialist**.
It is blocked before reading an image or making a model request in Aster mode.
There is no implied Aster image capability or automatic specialist exemption.
Voice capture and playback remain separate and unchanged.

## Shared contract and testing

`aster_provider/` is a byte-identical vendored copy of the stdlib-only shared
preparation contract, protocol `aster.app-provider.v1`, package version
`1.0.0-preparation`. The source hashes are recorded in
[`ASTER_PROVIDER_VENDOR.json`](ASTER_PROVIDER_VENDOR.json). IdeaForge does not
modify the shared package or depend on an installation outside this repository.

The only production transport in this stage reports unavailable. Tests can
explicitly inject an `InProcessTestTransport` with exact task/schema capabilities
and correctly bound typed responses. Such output is marked `test_only`; passing
these fixtures is not evidence of a working or qualified live Aster model.

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```

The provider suite covers all 13 routes in Standalone, offline Aster, unavailable,
and unsupported modes, nested and background routing, raw/schema preservation,
request provenance, stale configuration/project completion, cancellation,
absolute deadlines, bounded input/output, pending discovery recovery, process
restart, explicit selector behavior, and vision separation. No tests require
network or live model calls. Native Tk layout requires a display; Windows voice,
real Aster/Ollama behavior and answer quality are not qualified by these tests.
