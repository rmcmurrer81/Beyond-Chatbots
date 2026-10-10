# Aster Workstation — October 10 presentation source copy

Aster is Kira Labs' experimental, local-first personal workstation assistant. The goal is a persistent creative partner that can converse, remember project context, coordinate applications and use reviewed tools through NewBrain.

**This copy contains the current selected Aster application source. Its production NewBrain reasoning connection is still unavailable.** Deterministic workstation features are real code; they should not be presented as evidence of general intelligence or ordinary conversation.

## October 10 presentation refresh

The current coherent application source remains `bdc57febdbfa17f572eaa1e0a95c56da066d1e25`, including the recovery-isolation increment already packaged here. The public files were rechecked against their recorded source blobs on October 10.

A newer research-bundle intake branch and the shared simulation workbench are **not included** in this copy. The bundle branch diverges from the recovery branch: copying its CLI wholesale would remove recovery-required handling. That combination needs its own review and execution checks before release. The workbench is still in development.

The sibling IdeaForge copy now includes the October 10 troubleshooting fixes. This does not activate Aster reasoning: the NewBrain folder remains an experimental reference package and no live reasoning connection is qualified. No new Aster runtime test passed during this refresh.

## Exact version and scope

- Selected coherent source: `rmcmurrer81/aster-workstation` commit `bdc57febdbfa17f572eaa1e0a95c56da066d1e25` (recovery-fault isolation candidate, including the preceding application foundation).
- Source main at preparation: `8108d71d5deccc9ff382390f646b8194a685cb0a`.
- Prepared October 10, 2026. Newer candidate code is included, with its unrun status retained.
- [Source manifest](SOURCE-MANIFEST.json) lists every included source file and original Git blob identity, exclusions and presentation edits.
- [Original source README](UPSTREAM-README.md) contains the longer architecture and historical development record. This presentation README takes precedence for what is actually included here.

The original repository remains private. No original repository branch is changed by this copy.

## What the implemented application can do now

- Open a Tk desktop or command-line interface for explicit local operations.
- Create an owner-selected local identity/state store, save requests and explicit memories, show history and corrections.
- Read/write files within its managed workspace, keep change history, offer recoverable trash and conflict-aware undo.
- Queue and explicitly execute supported finite jobs; inspect interruptions and recorded effects.
- Inspect local resource information and apply bounded pre-start admission rules.
- Import explicitly selected, hash-reviewed research exports and use cited local reference passages.
- Prepare unsent communication drafts and perform bounded PCM WAV edits.
- Open a reviewed website or encoded search in the default browser. A separate anonymous static reader handles explicitly selected public sources.
- Exercise deterministic, bounded JSON text-recipe abilities.
- Provide source prototypes for a web/phone companion and Android invitation UI.
- Provide original experimental vocal-fold/tract and synthetic vision scaffolds. These are research components, not fluent speech or general vision.

These are implementation descriptions. Not every path is requalified on the exact exported snapshot or your machine.

## What it cannot currently do

- Generate ordinary conversational answers or autonomously reason, plan, learn arbitrary subjects, write programs or conduct research.
- Use another language model as a hidden fallback. `talk` saves a request as `waiting_for_newbrain`.
- Provide a working live Aster provider for IdeaForge, HumanoidResearcher or BlueBook.
- Recognize arbitrary people/objects, continuously watch the screen/webcam or understand a movie.
- Produce fluent speech using the vocal-fold experiment. Its outputs are bounded experimental vowel-like audio.
- Sign into accounts, create accounts, submit forms or send messages using the included application foundation.
- Offer a production-deployed phone service or a verified Android APK.

Adding NewBrain files alone will not complete these capabilities. Each needs a compatible, qualified interface and its own evidence.

## NewBrain connection and the morning release

The application declares a proposed `aster.newbrain.proposed.v1` request boundary; it is not a claim about the current NewBrain API. The shared app-provider package declares `aster.app-provider.v1`.

This copy deliberately contains **no historical vendored NewBrain core, weights, checkpoints or personal state**. Codex's separately approved NewBrain presentation release can be added to Beyond-Chatbots independently. No code here automatically finds or executes that future folder.

Before integration:
1. Pin the approved NewBrain release and inspect its actual callable interface and dependencies.
2. Supply a reviewed adapter to Aster's request/cancellation/result contract.
3. Use a fresh Aster-owned state and synthetic fixtures, keeping other people's identity and memory separate.
4. Test unavailable/incompatible inputs, cancellation, restart, source provenance and no-fallback behavior.
5. Measure generated answers, learning and false recall separately from persistence and mechanical tests.

The five shared `aster_provider` source files in this snapshot were compared byte-for-byte with the IdeaForge presentation source during preparation; that establishes contract-source identity only, not a live connection.

## Windows setup

Download Beyond-Chatbots using **Code → Download ZIP**, extract it fully, and open PowerShell in the outer `aster` folder containing this README, `launch_aster.py` and the inner Python package `aster/`.

Install Python 3.10+ with Tk support if needed. The deterministic core uses Python's standard library and does not download a model.

```powershell
$state = Join-Path $env:LOCALAPPDATA 'Aster-Presentation\state'
python -m aster --state $state status
python -m aster --state $state desktop
```

Use the same state directory across launches. Keep it outside the public checkout and cloud-synced folders. Close the desktop before accessing its state from another CLI process.

A small explicit demonstration:

```powershell
python -m aster --state $state talk "Help me design a gripper"
python -m aster --state $state remember "This demo uses metric units" --source user
python -m aster --state $state history prompts
python -m aster --state $state provider-status
```

Expected: the request is saved; no generated AI answer appears. For command details, use `python -m aster --help`. No installation, desktop test or device access was performed during publication.

## Included experiments and exclusions

Original Aster physical voice source is included; shared files later retained in NewBrain originated in Aster. This does not qualify biological realism or fluent language.

Excluded: historical NewBrain vendor directories, personal identity/memory/state, private raw result archives, private comparison inventories, GitHub Actions workflows, and prerecorded voice/media assets. Consequently voice-preview commands, vendor-dependent experiments, and tests requiring omitted assets cannot all run from this public package. Do not substitute private files or run a blanket suite and call the omissions a full pass.

Offline TLS fixture keys and certificates are excluded from this public copy. Transport tests that require those fixtures are unavailable here; this omission is not a runtime pass.

## Actual verification and limitations

Publication work used source inspection, exact source-blob comparisons, JSON parsing, privacy/exclusion checks and remote file verification. **No Python, learning, UI, browser, audio or model test was executed for this exported snapshot.** Runtime results are UNRUN.

Historical upstream milestones remain historical:
- Source `32f1442074e903c78edd859913a33b941305ba6d`: Windows 152 passed / 157 collected, 5 skips; Linux 136 passed / 157, 21 skips.
- Source `ea2f0168bd6b88de38f4cecf7210877478a81869`: Windows 229 passed / 237, 8 skips; Linux 213 passed / 237, 24 skips.
- The current recovery-isolation increment has eight authored methods covering sixteen scenarios, UNRUN. Older passes do not qualify it.

See [validation history](docs/VALIDATION.md) and [reliability scope](docs/RELIABILITY.md). Links into the private original repository may be inaccessible to attendees. Historical raw archives referenced by source docs are not included.

## Goal and development path

Qualify reliable app mechanics first; then connect an independently tested NewBrain instance; then validate conversation, memory use, speech, perception and app coordination in controlled steps. Identity/state belongs to Aster, while the reusable brain architecture remains separate.

Source access is provided for the presentation. Project licensing remains pending the owner's choice; public availability does not grant a new blanket open-source license. Preserve dependency and third-party terms. No paid compute or GitHub Actions is needed to inspect this package.

## Shared NewBrain package

See [NEWBRAIN-CONNECTION.md](NEWBRAIN-CONNECTION.md) for the shared folder layout and experimental connection plan. The current incomplete NewBrain kit is not a verified replacement for Aster's conversational provider.
