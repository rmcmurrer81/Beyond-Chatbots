# IdeaForge and the generic NewBrain release

This is a connection plan. The published IdeaForge implementation is unchanged, and no live NewBrain integration is qualified.

## What is available

The separately prepared [NewBrain folder](../NewBrain/README.md) contains a small GLIF starter and routing/state research references. It is not the complete private NewBrain model, an ordinary conversational backend, or an accepted useful-memory/learning service. Its dependencies are documented in [NewBrain requirements](../NewBrain/REQUIREMENTS.md); the starter uses the standard library, while some routing references need NumPy.

Keep the folder beside IdeaForge at the repository root. Copying it into IdeaForge or changing a model name does not create a compatible adapter.

## Keep the current app behavior

Use IdeaForge's existing [README](README.md) for setup: Python 3.11+, the listed packages and local Ollama/model dependencies for Standalone, followed by the existing Windows installer and launcher. No setup, model or app test was run while preparing this document.

The README documents Standalone as the default and the provider-selection commands in `ai.provider`. The current `ai_provider.json` selects `standalone`; it is a provider-selection record, not a NewBrain model configuration. Selecting Aster currently reports unavailable. Do not relabel existing Ollama output as NewBrain or introduce a hidden fallback.

## Proposed connection

A future reviewed adapter would connect IdeaForge's existing Aster provider contract to a qualified Aster/NewBrain service. It must pin the actual callable interface and dependencies, preserve project identity and citations, and support cancellation, deadlines and explicit unavailable/error results. The matching shared provider source is not proof of a live transport.

Use a fresh app-owned state and synthetic examples. Measure answer quality, useful recall, false-memory resistance, corrections, restart retention and latency separately; historical persistence checks do not establish these outcomes.

Reusable task skills or abstract knowledge may later transfer through reviewed admission and provenance rules. Maya's private identity, episodes, conversation history, memories, state, checkpoints and exact appearance assets are excluded. No skill transfer was executed or accepted here.
