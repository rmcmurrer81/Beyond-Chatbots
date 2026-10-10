# IdeaForge — October 10 presentation source copy

IdeaForge is Kira Labs' conversational invention and prototyping workspace. Its goal is to help turn an ambitious idea into research questions, evidence, buildable subsystems, parts, tools and progressively tested prototypes.

It keeps separate projects, equipment, references and troubleshooting history so work can continue across sessions. Fictional inspiration is a starting goal, not evidence that its mechanisms are buildable.

## Exact version

- Selected coherent source: `rmcmurrer81/IdeaForge` commit `1e461c49518b9356780ed4a1a24e17f783eab366`, including the reviewed printer-fit, photo/OCR, parameter and evidence work.
- Source main at preparation: `ab021755cf49575fa1765b8c94e4b3898f0c1372`.
- Prepared October 10, 2026. This includes newer candidate source whose runtime checks remain UNRUN.
- [Source manifest](SOURCE-MANIFEST.json) records every source file, its original Git blob and the presentation redactions.
- [Original README](UPSTREAM-README.md) provides detailed historical usage. This presentation README controls the status of this copy.

The original IdeaForge repository remains private and unchanged.

## What is implemented now

- A multi-project desktop workspace with typed conversation, saved project context, selected visual references and explicit project switching.
- Local project/equipment inventories and persistent troubleshooting records.
- Research collection using web, arXiv and OpenAlex sources, with bounded background queues, stored results and discovery tracking.
- Saved-passage lexical retrieval and project-specific citations; references remain attributed and generated summaries are labeled.
- Optional Windows hands-free input and installed female speech output with pause/stop controls.
- Parametric enclosure planning and OpenSCAD export; supported mesh/dimension checks.
- A 3D assembly workspace and narrowly scoped engineering pilot, rather than a general engineering simulator.
- New source for local PDF passage evidence, reviewed parameter links, grouped photo inventory, bounded local OCR review, selected-printer fit and explicit metadata-only Aster result bundles.

The latest additions have source/review evidence, but their exact exported runtime is not newly verified. Read the UNRUN notes below before demonstrating them.

## What a photo inventory entry means

Several photos can be associated with the same physical item, reviewed and projected into the equipment inventory. OCR text and manufacturer/model suggestions require review. A label or plausible image is not proof of a board model, electrical rating, ownership or quantity. This snapshot does not supply a trained general-purpose parts-identification system.

See [photo inventory](docs/PHOTO_INVENTORY.md), [OCR flow](docs/PHOTO_OCR_FLOW.md) and [printer fit](docs/PRINTER_FIT.md). Printer fit screens geometric bounds and specified margins; it cannot certify printability, strength, material safety or manufacturing quality.

## Current model choice versus intended NewBrain integration

**Standalone remains the default.** Existing conversation and model-assisted interpretation use local Ollama with the configured `qwen3.5:9b` model. Optional legacy image troubleshooting uses `qwen3-vl:8b`. These are disclosed existing IdeaForge dependencies. They are not NewBrain and must not be presented as NewBrain results.

The prepared **Aster** selection currently reports unavailable. It neither falls back silently to Ollama nor accesses Aster's private memory.

From the IdeaForge folder:

```powershell
python -m ai.provider
python -m ai.provider --provider aster
python -m ai.provider --provider standalone
```

The five shared `aster_provider` files were compared byte-for-byte with the Aster presentation source. This proves matching contract code only. There is no qualified live transport or reasoning service here.

## What remains unavailable until a qualified NewBrain connection exists

IdeaForge cannot presently use Aster/NewBrain to generate ordinary engineering conversation, interpret arbitrary project instructions, learn new knowledge reliably or autonomously plan its research. Aster mode must remain visibly unavailable.

Adding a NewBrain folder alone will not solve this. A reviewed adapter must establish compatible requests, outputs, project identity, cancellation, deadlines, provenance and explicit failure behavior. Learning, recall, false-memory resistance and answer quality need independent tests.

Even a completed NewBrain will not automatically create accurate CAD, valid simulations, correct parts identifications or safe hardware. Those tools, data and engineering checks require separate qualification.

## Long-term goal

A conversational workspace that remembers each project's measured constraints, uses owned equipment, finds useful primary research, explains uncertainty, proposes realistic prototypes and records why a design changed. Aster should eventually supply the main NewBrain-based assistant while IdeaForge retains its specialist project, evidence, CAD and validation tools.

## Windows setup

1. Download Beyond-Chatbots using **Code → Download ZIP** and extract it fully.
2. Open the `IdeaForge` folder containing this README and `IdeaForge.bat`.
3. Install Python 3.11+ if needed.
4. For the existing Standalone chat path, install Ollama and make the configured local model available. Model size/RAM and download requirements are separate from the source package.
5. Run `install_windows.bat`. It creates a local virtual environment and installs the listed Python packages. It does not bundle model weights.
6. Run `IdeaForge.bat`.

For hands-free setup, follow [the voice guide](ai/HANDS_FREE.md). It explicitly builds the fixed Windows System.Speech helper with installed Windows components. Voice starts off and requires the appropriate installed recognizer, voice and microphone. The helper is shared with the other Kira research apps, so only one should own it in a Windows session.

Optional tools:
- OpenSCAD for supported STL export.
- PyBullet or the separately listed engineering-pilot dependencies for scoped simulation work.
- Optional PDF/OCR dependencies described in their guides.
- No external software was installed or run during publication.

Do not upload generated projects, equipment inventories, photos, microphone data, private documents or model state into this public repository.

## What has actually been tested

**No runtime tests were executed on this exact exported snapshot during this publication.** Current candidate runtime status is UNRUN. Source/manifest checks do not demonstrate model quality.

Historical receipt: [October 6 provider preparation](docs/test-receipts/2026-10-06-aster-provider-preparation.json) reports 181 collected, 180 passed, one native-Tk/display skip in its recorded Linux environment. It used injected providers and does not qualify a live NewBrain connection.

Later PDF, parameter, photo/OCR and printer-fit additions preserve their UNRUN statuses in [test receipts](docs/test-receipts/) and [source-only results](test-results/). The printer-fit increment has twelve new scenario methods plus one modified existing method, with zero executed for that receipt. Source review passes are not runtime passes.

A future qualified local test can use:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Optional dependencies and a graphical session affect coverage. Report skips, failures and unavailable dependencies individually. No real printer, load-bearing prototype, live model quality or physical hardware was qualified by this copy.

## Packaging and rights

Included: generic application source, tests, documentation and appropriate synthetic examples. Omitted: workflows, personal project/state/media, credentials and unapproved NewBrain source. A few receipt fields containing private coordination or a private workspace path were redacted; original source IDs and runtime outcomes are preserved in the manifest and receipts.

No blanket new license is granted by this presentation copy. Check dependency, model, dataset and asset terms before redistribution or commercial reuse. See the dependency files and upstream notices.

## NewBrain connection

See [NEWBRAIN-CONNECTION.md](NEWBRAIN-CONNECTION.md) for copying the shared NewBrain folder and preparing an experimental adapter. The current incomplete kit is not a verified replacement for IdeaForge's existing model provider.
