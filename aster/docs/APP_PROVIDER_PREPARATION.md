# App-provider contract preparation

This additive preparation defines a bounded, versioned seam for IdeaForge,
Humanoid Researcher and BlueBook to select Aster explicitly. It does **not** make
Aster a functioning AI provider. Production NewBrain remains unavailable, there
is no reasoning fallback, and the existing `talk()` persistence semantics are
unchanged. Nothing starts a listener, opens IPC, accesses Store, loads a model,
creates credentials, changes permissions or connects to another app.

## Readiness without side effects

Run `python -m aster provider-status` to inspect preparation status without
opening a state directory. `aster.provider_gateway.status()` exposes the same
read-only hook. `aster_provider.readiness().to_dict()` reports:

- `reachable: false`: no production transport exists
- `compatible: false`: no remote handshake has been verified
- `qualified: false`: no NewBrain task/output capability is qualified
- `production_available: false`, an explicit reason, and `fallback: null`

An explicitly injected `InProcessTestTransport` can report reachable/compatible/
qualified **test-fixture** flags. It always reports `test_only: true` and
`production_available: false`; every fixture output carries test provenance.
Passing fixture tests cannot qualify NewBrain or a real app connection.

## Deliberate selection

The optional app-root `ai_provider.json` has exactly these four fields:

```json
{"protocol":"aster.provider.selection.v1","provider":"aster","app_id":"ideaforge","revision":1}
```

Allowed app IDs are `ideaforge`, `humanoid-researcher`, and `bluebook`. Provider is
`standalone` or `aster`. Revision is a nonnegative integer. There is no automatic
switch and no ambient path, environment variable or global selection lookup.
The app passes its own root path explicitly; a missing file defaults to its
original standalone provider. Malformed, unreadable, oversized, duplicate-key,
wrong-app or unsupported configuration fails closed rather than silently choosing
standalone. The file contains no endpoint, password, token or project content.

Use `capture_selection(path, app_id=..., project_id=...)` once at the beginning of
an operation. It returns a frozen `ProviderSelection` that binds the current
project, app, provider, revision and exact-file SHA-256. The root file selects an
app's provider only; it does not grant cross-project context. Pass that same
selection through nested calls. For an explicitly created child project,
`selection.for_project(new_id)` changes only the request-level project binding
without rereading or switching the provider. Context still must match that
project exactly.

`save_selection(path, selection)` atomically saves an explicitly requested local
choice and returns its captured file digest. Apps own review/UI and whether to
save it. `ensure_selection_current(selection, path)` belongs immediately before
publishing an operation result; it rejects a file changed or removed since
capture, including changes that reuse the same revision. Apps must also recheck
their own project/document/input revisions before committing results.

## Client integration

```python
from aster_provider import capture_selection, invoke_text, deadline_after

selection = capture_selection("ai_provider.json", app_id="ideaforge", project_id="project-1")
result = invoke_text(
    [{"role": "user", "content": "Bounded project input"}],
    lambda: original_standalone_call(original_payload),
    app_id="ideaforge", project_id="project-1", task="chat",
    selection=selection, session_id="operation-1", deadline=deadline_after(30),
)
raw_response = result.text
metadata = result.provenance.to_dict()
```

The standalone callback takes **no arguments**, so the app can close over its
original payload, captured model configuration, response limits and strict
validators. `ainvoke_text` has the same arguments and awaits an async callback.
`ProviderText.text` is raw text: existing app JSON/quote/citation validation must
still run. Aster routing never invokes the standalone callback, even after an
unavailable, unsupported, malformed, cancelled or expired response.

Optional fields are `schema`, `context`, `options`, `session_id`, `request_id`,
`cancellation`, `deadline` and injected test `transport`. `schema` may be absent
(plain `text`), a stable schema ID, or a bounded JSON-schema object. Its canonical
hash identifies a mapping on every request. `options` allows only generation settings (`temperature`, `num_predict`,
`max_tokens`, `top_p`, `top_k`, `seed`, `stop`). It rejects tools, endpoints,
runtimes, memory, training and format/schema overrides; output schema belongs in
the typed `schema` field.

Deadlines are absolute Unix timestamps (`time.time()`), **not monotonic-clock
values**. `deadline_after(seconds)` constructs one. They are checked before and
after calls; async awaits are bounded by the remaining duration. A synchronous
callback cannot be forcibly stopped by this library: late output is rejected
after it returns. This is not hard CPU/memory isolation. `CancellationToken` has
`cancel()` and a boolean `cancelled` property; a no-argument boolean callable is
also accepted. Cancellation is checked before/after calls and at app commit
boundaries with `guard()`. Cancellation does not imply rollback of unrelated
work already performed by the original standalone provider.

Errors derive from `ProviderError`: `ProviderUnavailable`,
`UnsupportedCapability`, `InvalidRequest`, `ProviderCancelled`,
`DeadlineExceeded`, `ReplayMismatch`, `ProtocolMismatch`, and `StaleSelection`.
Each exposes `code` and `to_dict()` with `reason` and `fallback: null`. Apps should
show an honest blocked/cancelled status and preserve unfinished work.

## Contract and isolation

`aster.app-provider.v1` binds every Aster request and response to app, project,
session, request ID, task, exact schema identity, captured config revision/digest
and the complete canonical input digest. Responses with any mismatched binding
are rejected. Provenance contains these bindings and no prompt/context contents.
Standalone results retain the operation identifiers and configuration provenance;
their input digest is empty because they are not Aster contract requests.

Limits are UTF-8 bytes: 64 messages, 65,536 bytes per message/context record,
32 context records, 524,288 bytes for the full request, 16,384 schema bytes,
8,192 options bytes, and 262,144 output bytes. JSON is limited to 16 levels and
10,000 nodes; non-finite numbers, non-JSON objects, invalid Unicode and unbounded
integers are refused. Message roles are labels only. All messages and context
are marked untrusted. Context is exclusively project/transient, app/project-
bound. Global personal memory and training are prohibited regardless of prompt
instructions. No default request is saved to Aster history or long-term memory.

Task/output-schema capabilities must be explicitly advertised. A capability
matches an exact task and exact schema ID. `Capability(task, "json-schema")` is a
specific schema-kind capability for a supplied JSON-schema **object**, useful
for BlueBook's per-request passage-ID enums. The exact schema hash still appears
on request/response/provenance. This does not allow a task wildcard, an arbitrary
stable schema-ID wildcard, or bypassing the app's strict response validator.

The synchronous and asynchronous fixture seam accepts only typed
`ProviderResponse.for_request(request, text)` responses. For example:

```python
from aster_provider import Capability, InProcessTestTransport, ProviderResponse
fixture = InProcessTestTransport(
    lambda request: ProviderResponse.for_request(request, "explicit test fixture"),
    capabilities=[Capability("chat", "text")],
)
```

Fixture handlers are trusted, explicitly injected test code. Input text is never
executed. Production transport stays `UnavailableTransport`; no arbitrary
transport object, runtime discovery or endpoint setting is accepted. Replay
state is bounded per fixture instance (128 requests by default, maximum 1,024),
never global or persistent. An identical request-ID/digest retry returns the
same response; changed input/scope, concurrent duplicates and uncertain failed
requests are rejected. At capacity, new requests fail instead of evicting replay
protection. Tests use independent instances for separate operations.

## Verification scope

`tests/test_app_provider.py` covers default unavailable/no fallback, selection
capture/config races, scoped context, adversarial input/output limits, capability
negotiation, mismatched response bindings, replay isolation, cancellation,
deadlines, sync/async callbacks, and Store-free status. These are offline
engineering fixtures, not generated answer evidence, app quality evaluation,
production integration, Windows desktop qualification or live NewBrain tests.
The retained test receipt records exact commands, results and unrun limits.

The shared `aster_provider` package is standard-library-only and intentionally
copied identically into the three app repositories for this preparation stage.
It is not installed as a service or downloaded dynamically at runtime.

Retained local evidence: [initial exact-main receipt](../test-results/app-provider/2026-10-06/receipt.json) and [reviewed voice-head stacked receipt](../test-results/app-provider/2026-10-06-stacked-voice/receipt.json). The latter preserves the complete reviewed physical-voice tree and reruns the core aggregate; it does not replace that experiment's separate native/numerical qualification.

The initial provider PR native foundation run is retained as an [honest failed-run observation](../test-results/app-provider/2026-10-06-native-ci-initial/observation.json): The full initial matrix finished with 12 passing checks and three Windows failures. Foundation encountered two upstream physical-voice test path-normalization assertions; the Windows text-learning aggregate and physical-voice contracts also failed while their recorded numerical/demo stages passed. Corrected upstream tests are imported without changing the provider package.

The [corrected voice-head local receipt](../test-results/app-provider/2026-10-06-corrected-voice/receipt.json) records the provider focus and complete core aggregate rerun against the exact reviewed correction, preserving the earlier outcomes.

The final additive refresh is bound to [merged voice main](../test-results/app-provider/2026-10-06-final-main/upstream-binding.json). The voice owner's [release-verification bundle](../test-results/physical-voice/release-verification/README.md) is preserved unchanged, including exact corrected-head and post-merge CI/artifact bindings. These upstream results do not assert that the refreshed provider PR itself passed CI.

The [final merged-main local receipt](../test-results/app-provider/2026-10-06-final-main/receipt.json) records one more complete focus/core-aggregate pass after the unchanged release bundle was included. Refreshed provider exact-head CI remains a separate publication gate.
