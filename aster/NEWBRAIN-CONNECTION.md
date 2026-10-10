# Aster and the generic NewBrain release

This is a connection plan. The published Aster implementation is unchanged. Its production NewBrain reasoning connection remains unavailable.

## Source placement and dependencies

Keep the separately prepared [NewBrain folder](../NewBrain/README.md) beside the outer `aster` folder at the repository root. It contains a small GLIF starter and routing/state research references, not the complete private model or a qualified conversation/learning service. Follow [NewBrain requirements](../NewBrain/REQUIREMENTS.md) for those references; adding files does not automatically connect Aster.

Use Aster's existing [README](README.md) for setup and supported commands. It describes Python 3.10+ with Tk support and a standard-library deterministic core, with state kept outside the public checkout. The separate `launch_aster.py` source also has its own isolated-startup and existing absolute-state-directory requirements; it was inspected, not invoked. No installation, UI, model, speech or test was run for this document.

## Preserve the current boundary

The README identifies `aster.newbrain.proposed.v1` as a proposed request boundary and `aster.app-provider.v1` as the shared app-provider contract. These names do not establish that the generic NewBrain source implements them.

Aster's documented `talk` behavior saves a request as `waiting_for_newbrain`; it does not generate an AI answer or secretly fall back to another model. Changing a model tag or importing the starter cannot make that boundary qualified.

## Proposed integration checks

Pin an actual supported NewBrain interface, then separately implement and review a compatible request/cancellation/result adapter. Use a fresh Aster-owned state and synthetic fixtures. Check incompatible inputs, explicit unavailability, cancellation, deadlines, provenance, restart and no-fallback behavior before describing the connection as working.

Measure conversational answers, useful retrieval, false recall, correction, learning and latency separately from deterministic mechanics and history preservation. None of those NewBrain outcomes was demonstrated by this source package.

Reusable skills or abstract knowledge may later transfer through reviewed admission, correction and provenance rules. Maya's private identity, episodes, history, memories, state, checkpoints and exact appearance assets remain excluded. This release performs no automatic private-memory or skill transfer.
