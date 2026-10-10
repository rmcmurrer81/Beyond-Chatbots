# Aster Workstation

**Aster is an original, feminine-presenting personal assistant and long-term creative partner being built around NewBrain, with her own persistent identity and a local-first workstation home.**

The goal is an assistant you can talk with naturally, work alongside, teach about your projects, and reach from your phone or laptop. She should help turn ideas into research, plans, software, and carefully tested prototypes, while being candid about uncertainty and respectful of your control over your computer and life.

**Today this repository is a working local desktop/CLI foundation, not a working conversational AI.** It saves requests, maintains Aster's own identity and explicit memories, manages bounded workspace files and finite jobs, and exposes reviewable research exports and ability proposals. NewBrain is the only intended reasoning backend. Until a qualified NewBrain interface is available, requests remain `waiting_for_newbrain`. There is no Qwen, Ollama, provider API, canned conversational answer, or other reasoning fallback.

This README separates the intended Aster from the software that has actually been implemented and tested. A roadmap item, voice audition, passing fixture, or interface proposal is not evidence that the corresponding intelligence or real-world capability exists.

## Optional synthetic vision experiment

A separate [vision lab](docs/VISION_EXPERIMENT.md) compares a fixed pixel-based
component extractor with the original NewBrain preprocessing, using fresh
color/shape learners, held-out synthetic layouts, strong baselines and explicit
unknown/overlap failures. Its source pins and test results stay in this repository.
This is a small perception experiment. Webcam/screen capture, real-world scene
understanding, OCR, people recognition and following a video remain unavailable.

## App-provider preparation

A versioned, bounded [app-provider contract](docs/APP_PROVIDER_PREPARATION.md)
prepares deliberate provider selection for IdeaForge, Humanoid Researcher and
BlueBook. `python -m aster provider-status` reports readiness without opening
Aster state. Production remains unavailable: there is no listener, live app IPC,
qualified NewBrain provider or reasoning fallback. Only explicitly injected
in-process test fixtures can exercise the seam; `talk()` is unchanged.

## October 6 experimental hearing dependency repair

A separately pinned opt-in experiment now contains the 20 exact generic hearing
modules and their six role maps. Fresh synthetic compatibility tests exercise
bounded learning, causal PCM, frozen controls and complete decision-state restore.
The original process entries still require isolated CPython 3.14.4; Python 3.12
must refuse those entries. [Scope, tests and retained results](docs/HEARING_COMPATIBILITY.md)
explain what has and has not been verified. This does not activate a production
brain, microphone, speech recognizer, network service or conversational fallback.

## October 5 reliability update

The [current upgrade record](docs/UPGRADE_2026_10_05.md) covers opt-in phone text while the desktop stays open, transactional experimental learning/observer checkpoints, exact old/new NewBrain source pins and retained rollback. The earlier tone-retention pin remains an unqualified candidate. Its original missing-dependency admission result is preserved; the separate October 6 generic dependency experiment does not qualify a runnable brain replacement. Local results and native GUI evidence are retained; exact-head CI and independent review remain separate release gates.

## October 5 supporting modules

Six bounded local modules are now available through `support` CLI commands and the
existing desktop's **Voice & status** tab: reviewed text-recipe abilities, private
memory retrieval and correction controls, a cited workspace reference library,
local communications exports and unsent drafts, reversible PCM WAV trims, and
resource-admission budgets. See [the usage and capability guide](docs/SUPPORT_MODULES.md).
No live accounts, arbitrary code execution, additional model, video/TTS/avatar
executor, GPU worker, user-PC install or public service is activated.

A separate upstream comparison was prepared for the owner. Detailed comparison
documents and external-source audit metadata are withheld from this publication.
The tested Aster component pin and unavailable production backend are unchanged.

## October 6 browser handoff

The **Browser** tab and `python -m aster browser` commands can open a reviewed
HTTP(S) website/source URL or an exactly encoded Google search in the default
browser. Nothing opens automatically, and launch acceptance does not prove a
page loaded. This is separate from webpage reading, form control, account
sign-in, and production reasoning. See [Browser actions](docs/BROWSER_ACTIONS.md)
for review steps, safety limits, and retained test evidence.

## Anonymous public source reader

The same **Browser** tab now has **Read public source** and **Follow selected
link** controls. `python -m aster.browser_public` exposes the same bounded static
reader without a browser or account. It extracts untrusted public text, shows
provenance, and follows only an explicitly selected source-owned link. No
JavaScript, login, forms, profile reuse, automatic redirects or background
browsing is enabled. See [Public reader](docs/PUBLIC_READER.md) for exact limits,
CLI usage, and the separate offline/native/public qualification gates.

## Contents

An optional [artificial voice-box experiment](docs/VOICE_BOX_EXPERIMENT.md) now
exports original, bounded vowel-like audio from a glottal-source/formant model.
It includes an explicit adapter from observed synthetic text-lab results,
checkpoint replay and measured PCM receipts. It does not replace the existing
voice, produce fluent speech or activate production NewBrain.

The next optional [physical phonation stage](docs/PHYSICAL_PHONATION_EXPERIMENT.md)
adds pressure-driven two-mass vocal folds, contact, an articulated oral/nasal tube,
anti-alias filtering and owner-bound waveform replay. It exposes explicit motor
controls and a saved experimental brain-output adapter. Its separate numerical
and independent-review evidence is retained; natural speech, anatomical fidelity
and production conversational intelligence remain unqualified.

An optional [synthetic text-learning experiment](docs/TEXT_LEARNING_EXPERIMENT.md)
now provides fresh Aster-owned token learning, equal-exposure teaching comparisons
and independent-process restore checks. It uses separately installed pinned NumPy,
preserves all observed mistakes, and does not activate Aster's production brain.

- [Vision and personality](#vision-and-personality)
- [Current capability map](#current-capability-map)
- [Quick start](#quick-start)
- [The desktop experience](#the-desktop-experience)
- [NewBrain, identity, and learning](#newbrain-identity-and-learning)
- [Memory and project continuity](#memory-and-project-continuity)
- [Workspace, jobs, and recovery](#workspace-jobs-and-recovery)
- [Startup, reliability, and memory pressure](#startup-reliability-and-memory-pressure)
- [Research and connected applications](#research-and-connected-applications)
- [Creating programs and new abilities](#creating-programs-and-new-abilities)
- [Voice and offline operation](#voice-and-offline-operation)
- [Phone, laptop, and future AR clients](#phone-laptop-and-future-ar-clients)
- [Inventing and building responsibly](#inventing-and-building-responsibly)
- [Permissions, privacy, and threat boundaries](#permissions-privacy-and-threat-boundaries)
- [Architecture and repository guide](#architecture-and-repository-guide)
- [Validation and acceptance milestones](#validation-and-acceptance-milestones)
- [Development principles and costs](#development-principles-and-costs)

## Vision and personality

### Who Aster should be

Aster should feel like a consistent collaborator rather than a disconnected set of command buttons. Her intended presentation is warm, adult, feminine, curious, capable, and conversational. She should develop continuity through her own authorized experiences and records, remember corrections, and help carry work forward across sessions.

Her inspiration includes the idea of E.V. in *Spider-Man: Brand New Day*: an assistant woven into a person's work and surroundings. That is a creative reference, not a specification copied from a fictional character. Aster should have an original name, voice, visual identity, dialogue, and relationship with her owner. She is not an actor impersonation, voice clone, or reproduction of a copyrighted character's persona.

Aster's intended behavior includes:

- **Natural conversation.** Understand the current exchange, respond in an appropriate tone, ask useful questions, and avoid repetitive scripted acknowledgements.
- **Independent judgment.** Disagree respectfully when an assumption seems wrong, explain why, and update her view when evidence changes. Being supportive should not mean agreeing with everything.
- **Useful initiative.** Notice an unfinished task, a failed operation, a relevant discovery, or a decision that needs attention. Bring it up when useful rather than constantly demanding attention.
- **Respectful interruption.** Eventually support being interrupted, stopping speech or work promptly, and returning to the right point. Her own interruptions should be proportionate to urgency and the user's preferences.
- **Honest capability reporting.** Distinguish what she knows, what a source says, what she inferred, what she tried, and what remains untested. Never narrate an action that did not happen.
- **Steady collaboration.** Help break an ambitious idea into achievable experiments without dismissing it or pretending that enthusiasm proves feasibility.
- **User control.** Offer choices where the decision belongs to the user, honor stop/cancel, and make consequential actions reviewable.
- **Appropriate companionship.** Be pleasant and engaging while preserving the user's autonomy and relationships. Do not pressure the user into dependence or claim exclusive understanding.

These are product goals, not claims about the present shell. Persistent records do not prove understanding; fluent speech would not prove consciousness. Any future NewBrain internal state or emotion-related observations must be described using the actual measured schema and evidence, without claiming human subjective feelings.

### What success would look like

A future qualified Aster could help you resume a project where you left it, explain a design tradeoff, locate the source behind a research claim, prepare a program change for review, speak in her consistent original voice, and report progress to an authorized companion device. She should continue useful local work during an Internet outage when all required local components are available.

The long-term goal is a dependable assistant that becomes more useful through accountable continuity and better capabilities. It is not unrestricted control of a computer, silent replacement of the user's decisions, or an excuse to call unfinished software complete.

## Current capability map

| Area | Implemented foundation | Still unavailable or future work |
| --- | --- | --- |
| Identity | Stable Aster identity in a selected private state directory | Qualified NewBrain-owned conversational continuity |
| Conversation | Saves user text and reports `waiting_for_newbrain` | Understanding, generated answers, dialogue, autonomous planning |
| Explicit memory | Literal/category/source search, dated decisions/preferences, correction families and recoverable visibility controls | Semantic search, secure erasure, proven model learning and cold recall |
| Desktop | Six-tab Tk control panel over deterministic local operations | General desktop or app control |
| Files | Scoped UTF-8 reads/writes, journaled changes, recoverable trash, conflict-aware undo | Arbitrary filesystem access or program execution |
| Jobs | Finite named actions, durable queue, one-at-a-time execution, pre-execution pause/resume/cancel | Autonomous task creation, continuous job runner |
| Research | Manual search links; read-only app registration discovery; explicitly selected local research snapshots | Autonomous web research, live research-app commands |
| Abilities | Immutable proposals plus bounded JSON text-recipe tests, source/test-bound reviewed installation, rollback and explicit runs | Arbitrary Python/shell execution, OS sandbox and code generation by NewBrain |
| Voice | Integrity-checked original prerecorded feminine voice audition | Live STT/TTS, spoken answers, listening or calls |
| Remote access | Separate locally tested web relay/bridge prototype; Android offline source prototype | Public deployment, verified Android APK/device use, background phone delivery, live voice |
| Resource care | Local RAM observation, optional estimated-RAM admission, queue ceiling and pre-start cancellation | Hard OS RAM/time limits, GPU workers, reclaiming model RAM or external-app shutdown |
| Reference library | Approved workspace folders, explicit UTF-8 file indexing and cited passages | PDF/OCR, Zotero and arbitrary personal-folder access |
| Communications | Reviewed local email/calendar/GitHub snapshots and unsent draft revisions | Live accounts, OAuth, provider APIs or sending |
| Media workshop | Bounded PCM WAV inspection and reversible frame-exact output copies | Video processing, live TTS/STT and avatars |
| Startup | Opt-in Windows sign-in startup helper and lifecycle records; not installed on the user’s PC | BIOS power-on, an installed system service, verified behavior on the user's own PC |

Startup/RAM has separate native automated qualification below; real registration and sign-in on the user’s PC have not been performed. See [validation](#validation-and-acceptance-milestones) and the exact branch head's checks.

## Quick start

### Requirements

- Python 3.10 or newer. CI uses Python 3.12.
- For the desktop: Tkinter and a graphical desktop session. The CLI works without a GUI.
- A private, owner-controlled state directory on a supported local filesystem.
- No third-party Python runtime packages are required for the core shell. There is no model download or Ollama requirement.

Obtain the intended reviewed branch of this repository and run commands from its root. A draft development branch may contain changes newer than the last validated main-branch milestone. This is source-run software, not a packaged installer.

### Windows / PowerShell

Use a local fixed NTFS directory outside OneDrive or other reparse/cloud-placeholder folders:

```powershell
$state = Join-Path $env:LOCALAPPDATA 'Aster\state'
python -m aster --state $state status
python -m aster --state $state desktop
```

Keep using the same `$state` path. Opening a different state directory creates a separate identity and history; it does not migrate the original Aster.

### Linux / POSIX shell

```sh
python -m aster --state "$HOME/.local/share/aster-state" status
python -m aster --state "$HOME/.local/share/aster-state" desktop
```

Linux has been exercised in development and CI. macOS has not been qualified just because it is POSIX-like. A missing Tk installation or display is reported explicitly; the program does not silently launch a server.

### First local actions

The following examples use the default `.aster-state` directory in your current working directory. Add the same `--state PATH` **before the command** if you selected another location. Close the desktop before using the CLI against its state, because the desktop holds the single-writer lock.

```sh
python -m aster status
python -m aster talk "Aster, help me design a gripper"
python -m aster remember "This project uses metric units" --source user
python -m aster write projects/hello.py 'print("Hello from Aster")'
python -m aster read projects/hello.py
python -m aster history prompts
python -m aster history memories
python -m aster history changes
```

The `talk` command saves your request; it does not produce an AI answer. The `.py` example saves source text; it does not execute it. JSON argument quoting varies by shell; use the desktop's job form if your shell alters quotes.

```sh
python -m aster queue research.links '{"query":"robot gripper compliant mechanism"}'
python -m aster run-one
python -m aster history jobs
python -m aster trash projects/hello.py
python -m aster undo CHANGE_ID_FROM_TRASH
python -m aster recover
```

Use `python -m aster --help` and each subcommand's `--help` for the available interface. Do not substitute arbitrary commands into job names: the queue accepts only implemented finite actions.

## The desktop experience

The [desktop guide](docs/DESKTOP.md) covers controls and confirmation behavior in detail.

1. **Requests:** Save and inspect pending requests. The list contains user messages, not fabricated generated conversation.
2. **Workspace:** Read, edit, save, or recoverably trash files inside Aster's workspace. Writes and destructive changes receive explicit review; unsaved editor drafts are protected by warnings, not automatically saved on close.
3. **Job queue:** Prepare a supported action, review it, and run the oldest queued job once. Selecting a different row does not change which queued job “Run next once” executes. Pause/resume/cancel apply before execution.
4. **History:** Inspect requests, jobs, memories, events, and file changes; explicitly undo an eligible change or reconcile interrupted work.
5. **Research exports:** Preview a supported local manifest and export, approve their exact hashes, and select an exact app/project snapshot. This does not connect to the running research app.
6. **Voice & status:** Inspect the supplied prerecorded voice and local app registrations. The voice preview is manually opened; no player or microphone starts automatically.
7. **Browser:** Read one anonymous static public source and explicitly follow a selected link. Separately, review a website/source URL or Google search for a default-browser handoff. Sign-in, forms, JavaScript and background browsing remain unavailable.

The UI uses a dedicated worker thread for Store, Files, jobs, and export operations. Controls and one-use confirmation tickets guard repeated submissions. Closing waits for accepted work to finish rather than killing an in-progress write. The current history view is bounded to recent entries; older data is retained in the journal.

Opening the window does not load a model, enable an ability, start a network listener, or drain a job queue.

## NewBrain, identity, and learning

### One reasoning backend

NewBrain is a separate research project. Aster is the workstation, identity, interaction, and permission layer around a future qualified instance of it. The two projects must have clear responsibilities:

- NewBrain development establishes the actual computational capabilities and measured limits of the core.
- Aster development supplies a usable interface, durable local state, scoped tools, approvals, and integration tests.
- Aster must not relabel another model's answer as NewBrain output.
- If NewBrain is absent, incompatible, times out, or fails qualification, Aster must say so and keep the user's pending work intact.

`aster.backend.BrainRequest` and `QualifiedNewBrain` describe a **proposed integration seam**, not an API already supplied by NewBrain. There is no endpoint setting, runtime loader, subprocess brain bridge, or enabling switch in this milestone.

The [integration record](docs/NEWBRAIN.md) identifies inspected NewBrain commits and the actual evidence available at those checkpoints. Experimental token decoding, value learning, observers, or documentation do not by themselves qualify a complete conversational assistant. Check the pinned record rather than assuming that a newer commit solves the integration gate.

### A fresh Aster instance

When a qualified core is available, initialize a fresh Aster-owned instance with its own subject ID and explicitly selected records. Do not import Maya's, Kira's, Robert's, or another subject's identity, memories, relationships, preferences, or personal history.

Core implementation and Aster's personal state are different things. Updating shared core code must preserve Aster's own identity and history through a reviewed migration with backups, compatibility checks, and a rollback plan. It must not reset her identity silently or merge unrelated subjects' records.

Existing research applications may have their own model dependencies or Qwen-based baseline behavior. That does not authorize using those models as Aster's reasoning backend. Discovering another app is not importing its brain or personal state.

### Safe source adoption

NewBrain inspection is read-only. The [isolated component lab](experiments/newbrain_adapter/README.md) copies two generic pure-Python components and tests, with exact commit/file hashes and retained rollback source. The current inspected pin is `df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef`; those component bytes are unchanged from the original pin, so repinning alone adds no capability. A separate [decision-retention075 candidate](experiments/newbrain_candidate/README.md) preserves current generic source but refuses runtime admission because five required modules are unpublished and private runtime/input bindings are excluded. No person identities, private memories/corpora, learned weights or restricted data were copied. The owner authorized project-source reuse; no broad public license is inferred. Never automatically pull and execute arbitrary upstream changes.

Before activating an adapter, demonstrate real NewBrain generation; subject isolation; explicit memory scope; absence, timeout, malformed-response, cancellation, restart, and no-fallback behavior; and measured resources on the intended hardware. Aster's tool permissions still apply even after that gate passes. A generated suggestion is not authority to execute it.

## Memory and project continuity

Aster's current persistence is explicit and inspectable:

- Stable identity belongs to the chosen state directory.
- User requests are saved even while no brain is connected.
- Explicit memories retain their source and can point to corrected/superseded records. [Private Memory](docs/MEMORY_LIBRARY.md) adds categories, source dates, literal search and recoverable hide/delete/restore. Normal CLI/desktop history respects visibility controls; exact-ID inspection and correction-family history retain the stored bytes. Deletion is not erasure.
- File changes, jobs, selected exports, and ability proposals retain history.
- Corrections append evidence instead of silently rewriting what happened.

Future useful memory should distinguish user instructions, observations, source claims, inferred conclusions, and later corrections. Project knowledge should retain exact project identity, source, version, date, and uncertainty. Information from one project must not leak into another merely because their names sound similar.

The current store is not an encrypted vault. Do not put passwords, API keys, payment details, or authentication tokens in prompts, memories, research exports, proposal source, or the workspace journal. Future service credentials belong in a separately reviewed secret store, with scoped access and revocation, not in Aster's personal memory.

Before migrating or backing up state, close cooperating Aster processes and use a consistent backup procedure for the state directory. History includes old file contents and trashed data; deleting a workspace file is not secure erasure. No purge command is implemented.

## Workspace, jobs, and recovery

### Managed files

Only files below `<state>/workspace` are editable through Aster's file tools. Ordinary text reads/writes are UTF-8 and bounded to 256 KiB. Absolute paths, traversal, links, hard links, and special files are rejected. Changes are journaled with before/after bytes for recovery and conflict-aware undo.

Undo checks the current file rather than overwriting a newer external edit. Recoverable trash preserves content in history. Program files can be stored as artifacts, but no shell, Python interpreter dispatch, or arbitrary process launcher is exposed.

### Finite jobs

Jobs are explicit named operations with bounded structured arguments. The durable queue supports pause, resume, and cancel before execution. `run-one` runs at most one job; it does not begin an autonomous loop.

The per-job budget is a **soft measured wall-time budget** of 0.1–30 seconds, not an OS-enforced CPU/RAM sandbox or hard timeout. A completed operation exceeding its budget is labelled accordingly. An atomic local write cannot safely be paused halfway through. Active work must finish or be reconciled after interruption.

### Interrupted work

`recover` compares journaled expectations with actual bytes, reports conflicts, and identifies interrupted jobs. It never blindly overwrites conflicts or replays a job whose side effect may already have happened. Inspect the file and history before retrying.

Process-crash recovery does not prove power-loss durability. Hardware failure, a full drive, hostile same-user software, and manually edited state can exceed the guarantees of this foundation. The SQLite page cap is approximately 64 MiB with default 4 KiB pages; workspace files also consume disk space. History is not silently pruned to hide a full database.

### Windows filesystem scope

The native Windows adapter supports **local fixed NTFS** only. Workspace-relative filenames are ASCII and canonicalized to lowercase journal keys; file contents and the state-directory name can contain Unicode.

Unsupported paths include UNC/network/device namespaces, symlinks, junctions, cloud placeholders and other reparse points, alternate data streams, DOS device/short-name aliases, trailing-dot/space names, and case-sensitive directories. A OneDrive-managed reparse folder is therefore not an acceptable workspace.

Native handles retain verified ancestors and use no-reparse create/read/rename/disposition operations. There is no weaker path-only fallback. Native tests cover these mechanisms, but they are not a security boundary against an administrator, hostile software under the same OS account, or drive remapping.

## Startup, reliability, and memory pressure

### Start after sign-in, preserve continuity

The intended everyday experience is to open the same Aster identity when the owner signs into Windows, recover transparently enough to explain what happened, and avoid restart loops. It is not permission to power on the PC through BIOS, bypass sign-in, install a privileged service, or keep the computer awake against the user's settings.

The startup helper uses an opt-in per-user Windows startup entry and a fixed checkout launcher. Its enable/disable path requires explicit local review. Running ordinary desktop or status commands does not install startup. The launcher uses the reviewed isolated Python invocation; do not call `launch_aster.py` directly with an improvised command. Consult the current startup helper's help and qualification record before enabling it.

The [startup guide](docs/STARTUP.md) explains the read-only plan and exact interactive
enable/disable workflow. From the checked-out repository on Windows:

```powershell
$state = Join-Path $env:LOCALAPPDATA 'Aster\state'
python -m aster --state $state status
python -m aster --state $state startup
python -m aster --state $state startup status
```

Enabling requires the reviewed plan digest and typing the displayed confirmation
phrase in a terminal. There is no noninteractive approval switch. Neither tests
nor cloud development enable startup on the runner or the user's PC. See
[recovery and RAM coordination](docs/RECOVERY_MEMORY.md) for its exact boundaries.

Lifecycle records distinguish clean and unclean sessions, check database health after taking the state lock, and preserve manual recovery/no-replay behavior. Restart-loop protection applies a bounded delay to automatic starts after repeated short unclean sessions. It does not erase requests or silently resume jobs.

### Reduce Aster's own demand first

The first resource-control goal is to avoid competing with the user's work. The current implementation samples system RAM through local OS counters and defers new Aster jobs when the admission policy cannot safely admit them. It does not kill a running operation, unload an unimplemented model, or reclaim a measured quantity of RAM.

The default thresholds are 90% used RAM to pause admission and 80% to permit it again, with hysteresis to avoid rapid oscillation. Unknown or stale observations defer work rather than pretending memory is available. Desktop observation does not trigger automatic job execution.

```sh
python -m aster memory status
python -m aster memory configure --high-percent 90 --resume-percent 80
```

Use the same selected state path as the rest of your session. Clearing pressure allows a later explicitly requested job attempt; it is not authorization to drain the queue. These safeguards are admission policy, not an OS memory reservation or hard resource sandbox.

### Other apps must be safe before they can close

A possible later feature is helping reduce idle workstation load. It must first pause or reduce Aster's own optional work. Closing Steam, iCloud, a browser, an email app, or another program would require app-specific support, permission, and reliable evidence that doing so cannot lose work or interrupt a game, download, synchronization, or transfer.

The [memory-relief planner](docs/MEMORY_RELIEF.md) is currently **diagnostic and always execution-disabled**. It collects no camera, input, app, or process observations; saves nothing; closes nothing; and contains no kill/force-quit dispatch. Its test evidence is simulated input, not proof of real app safety.

Requirements for any future implementation include:

- Optional presence evidence plus independent recent input-idle evidence; failing to see someone on a webcam is not sufficient evidence of absence.
- No continuous keystroke recording or assumed camera permission.
- Fresh app-specific evidence rechecked before each individual action, stopping when activity resumes or evidence becomes uncertain.
- Verified saved content, not a generic “save everything” shortcut.
- Browser URLs/bookmarks are not saved forms, unsent messages, uploads, or web-app drafts.
- An email draft is protected only when its exact current content and attachments are verified saved in the right account/location. Unknown state means leave it open.
- Graceful supported close only; no force killing to meet a RAM target.
- Explicit safeguards for Steam games/downloads/cloud saves and iCloud synchronization/transfers.

No external-app closure is enabled by this repository's current planner, favorable input flags, or an example app name.

## Research and connected applications

### Useful shared knowledge without blurred ownership

Aster should eventually help coordinate IdeaForge, Humanoid Researcher, and other approved tools. The goal is to carry the right project's questions and findings between useful applications while retaining their origin, not to merge every application's database or infer blanket access.

Current discovery is read-only:

```sh
python -m aster apps
python -m aster app-export --help
```

`apps` reads recent opt-in registrations without reading research records, importing app modules, or executing apps. A registration does not prove an app is running, grant Aster project access, or provide a command adapter. See [app discovery](docs/APPS.md).

The separate [research-export adapter](docs/APP_ADAPTERS.md) supports an Aster-owned versioned interchange format for JSON files already inside the managed workspace. The owner previews a manifest, approves its SHA-256, selects an exact registered app/project, then previews and approves an exact matching export. Capabilities control inspection versus reading; revocation remains explicit.

These are immutable local snapshots with owner-declared provenance. They are not proof that IdeaForge or Humanoid Researcher presently exports this format, and they are not live connections. Research text remains untrusted data rather than instructions to execute.

### Research behavior to build toward

A future qualified research workflow should collect primary sources, preserve links and relevant dates, compare conflicting findings, record negative results, and distinguish established evidence from a hypothesis. University research, official technical documentation, public code with an appropriate license, and reproducible experiments are useful starting points.

Today `research.links` only prepares manual search links. It does not fetch pages or claim to have read them. Real browsing, downloads, source ingestion, citations, and long-running research need their own reviewed adapters and acceptance tests.

### Email, GitHub, and online services

Future connections may let Aster help with specifically requested email, repositories, social accounts, and other services. Each needs an official supported authentication path, minimal scopes, clear recipient/project/account selection, secret storage outside personal memory, and explicit permission for consequential writes or sharing.

The current shell contains no general email client, GitHub agent, social posting integration, browser automation engine, credential manager, or account-creation agent. A requested destination must not become permission to explore or disclose unrelated private data.

## Creating programs and new abilities

Aster should eventually help turn an idea into a program or a narrowly scoped new ability. The intended development loop is:

1. Explain the requested outcome and scope.
2. Propose source changes and the capabilities they would need.
3. Inspect dependencies and provenance.
4. Run appropriate isolated tests and report actual results and failures.
5. Review the exact artifact and requested permissions.
6. Activate only an approved version through a separately qualified execution boundary.
7. Keep an audit trail and support stopping, revoking, and rolling back.

The original [ability registry](docs/ABILITIES.md) implements the inert artifact/review portion. It snapshots an existing workspace file, records its SHA-256 and declared permission labels, keeps append-only review/version history, and lets an approved artifact be selected for possible future activation or rolled back to an eligible earlier selection.

```sh
python -m aster ability propose gripper projects/hello.py --permissions-json '[]'
python -m aster ability list
python -m aster ability get PROPOSAL_ID
```

**Arbitrary program execution and activation stay disabled in that registry.** Permission labels are declarations, not grants. Selecting a proposal executes nothing. Review notes are owner-declared evidence; even a note saying “tests passed” does not mean this registry ran tests. The registry reports `tests_executed: false` and grants no capabilities.

The separate [Ability Workshop](docs/ABILITY_WORKSHOP.md) now runs a strict, bounded JSON text-recipe format. It performs actual in-memory example tests, binds owner review to those results and interpreter/source hashes, records explicit installation or rollback, and requires a separate exact-input run. This is a small deterministic text tool, not an OS sandbox or execution of proposed Python programs.

Aster must not silently expand her tool access, execute downloaded code, self-install abilities, or turn research text into instructions. Self-improvement is a reviewed engineering process, not an unrestricted self-modification switch.

## Voice and offline operation

### Aster's original voice

The repository includes an original synthetic adult feminine voice audition and style profile in `assets/voices/aster_warm_female20s_v1/`. The supplied WAV is 14.4 seconds, mono 24 kHz PCM16. Its bytes and metadata are pinned and checked; the [voice record](docs/VOICE.md) contains the hashes and provenance.

```sh
python -m aster voice
```

This read-only command reports the local preview path after integrity checks. Open that preview manually to listen. It does not create state, play audio, start a microphone, contact a service, or synthesize a new response.

The supplied sample was generated using Qwen3-TTS VoiceDesign. That is voice-asset provenance, not a Qwen reasoning fallback or a bundled TTS runtime. No model weights, donor recording, private cloned voice, or live generator was imported. The audition's spoken description of Aster is aspirational, not proof of current abilities.

Future speech needs separately qualified speech-to-text, text-to-speech, interruption handling, device permissions, voice consistency, latency, resource, and licensing checks. A synthesizer should speak actual authorized output; it must not invent a missing NewBrain answer.

### What survives an Internet outage

The current desktop, identity, saved requests, explicit memories, local files, history, and finite local jobs can work without Internet. Socket-denied tests cover local work and reopening pending requests and paused jobs. Connectivity returning does not automatically submit saved prompts or resume queued jobs.

A future entirely local NewBrain plus locally installed speech runtimes/assets could support offline conversation and speech. That is conditional on components not present in this foundation. Downloaded assets and resource qualification must happen before an outage; a prerecorded WAV cannot supply arbitrary new speech.

Manual search links can be prepared offline, but visiting them requires connectivity. A remote client away from the workstation cannot reach it during an Internet outage. The current web prototype has a bounded unsent outbox and reconnect deduplication; that is not a guarantee of always-on reachability or emergency delivery.

## Phone, laptop, and future AR clients

The target architecture keeps Aster's identity and reasoning at her workstation and lets authenticated clients exchange permitted messages or sessions. The workstation must be powered on, awake, and connected for away-from-home access. A phone UI is not another brain or a reason to upload all of Aster's state.

### Android source prototype

The [Android companion](android-companion/README.md) contains local invitation/session controls and an offline protocol model. It has no verified APK or physical-device run, workstation connection, microphone implementation, live voice, or carrier calling. Protocol tests are not APK validation.

### Phone/laptop web prototype

The [remote companion](remote-companion/README.md) contains a responsive web shell, bounded offline outbox, owner-scoped relay, and outbound-only workstation bridge. Local tests exercise queue delivery, duplicate handling, receipts, authentication roles, expiry, and restart mechanics. A delivery receipt means a prompt was saved, not understood or answered.

This is not publicly deployed. Secure enrollment, approved hosting, hardened production serving, background delivery, push permissions, and live voice remain separate work. The reference Python HTTP server must not be exposed directly as an Internet-facing production service. The relay is not end-to-end encrypted; its operator can read relayed messages. No accounts, persistent credentials, or public listeners are created by merely running the Aster desktop.

### AR and display clients

A future AR display could present an assistant interface, project references, visual guidance, or spatial content. That requires an actual chosen device, its supported SDK, rendering/input capabilities, calibration, performance, and network/privacy review. A text protocol or a proposed `display.ar` permission label does not implement AR.

All clients should share a reviewed, authenticated protocol with bounded actions and clear session control. Microphone/camera use needs explicit permission; ending a session must stop capture. Neither browser/PWA delivery nor Internet voice can be promised to behave like a cellular call under all background and network conditions.

## Inventing and building responsibly

Aster's long-term role includes helping explore original inventions: new software and tools, robotic assistants inspired by concepts such as Alpha 5, immersive or “holodeck”-like experiences, wearable systems and suit concepts, and practical mechanisms. Those are directions for research and incremental building, not claims that fictional technologies are currently possible.

A useful engineering process is to:

1. Define the desired effect and a measurable success criterion.
2. Separate known physics and available components from speculation.
3. Look for primary research, university work, official hardware documentation, and appropriately licensed code.
4. Compare the proposed idea with prior work; novelty is a question to investigate, not a promise.
5. Break it into the smallest simulation or bench experiment that can resolve an uncertainty.
6. Record assumptions, tolerances, units, failure modes, costs, and test results.
7. Review safety before increasing loads, energy, autonomy, or human contact.

CAD, physics simulation, control design, and fabrication require actual tools and validated adapters. Small two-link simulation/CAD pilots in related work are bounded experiments in separate repositories; they do not make this shell a physical engineer or a general robot controller.

For wearable or body-adjacent prototypes, photos/videos can support rough estimates only with known scale, calibration, viewpoint, and explicit uncertainty. Direct tape measurements, adjustable fit, low-risk plastic mockups, and measurement jigs are appropriate early aids. A plausible 3D model, image-derived dimension, or successful 3D print does not prove safe fit, load capacity, thermal/electrical safety, or suitability for powered human use.

Aster should help make these limits visible. High-energy, load-bearing, powered wearable, and human-contact systems require qualified review and real validation; she should not present speculative designs as safe instructions.

## Permissions, privacy, and threat boundaries

The project favors narrow, explicit, reviewable actions:

- **Local scope:** managed workspace files only; no arbitrary user-folder traversal.
- **Single writer:** an advisory process lock coordinates cooperating Aster processes. It does not stop hostile programs with the same OS privileges.
- **Inert content:** research exports, requests, and source proposals are data, not executable instructions.
- **Bound approvals:** exact artifact hashes, app/project identities, and one-use UI confirmations prevent stale or broadened approval.
- **No automatic execution:** opening Aster, reconnecting the network, selecting an ability, or updating source does not grant permission to run work.
- **Visible failures:** missing data, unknown resource state, unavailable models, conflicts, and interrupted jobs remain visible.
- **No credential memory:** future credentials must remain separate from prompts, personal history, logs, screenshots, and Git.
- **Separate sharing decisions:** importing a local record does not authorize publishing it or sending it to an external service.

Keep the state directory private and owner-controlled. It is unencrypted and includes requests, memories, research snapshots, file versions, and recoverable trash. The software does not claim protection against hostile same-user programs, administrators, physical access to an unlocked machine, or compromised operating systems.

The core desktop opens no network service. The optional remote prototype introduces a different threat model and must be reviewed separately before use. Camera, microphone, startup registration, public hosting, account connections, and external actions are not implied by downloading the repository.

## Architecture and repository guide

The current data flow is deliberately small: a local UI or CLI invokes a named operation; Store and scoped adapters enforce persistence and boundaries; the result is returned for inspection. The brain boundary stays unavailable. Remote source is separate and only deposits bounded text through the existing persistence path.

| Path | Responsibility |
| --- | --- |
| `aster/__main__.py` | CLI parsing and explicit command routing |
| `aster/backend.py` | Proposed NewBrain request protocol and honest unavailable behavior |
| `aster/storage.py` | Identity, SQLite persistence, events, memory and history |
| `aster/files.py`, `aster/windows_files.py`, `aster/platform.py` | Scoped file operations and platform safety boundaries |
| `aster/jobs.py` | Finite durable job queue and single-job execution |
| `aster/dashboard.py`, `aster/desktop.py` | Display-independent controller/worker and seven-tab Tk interface |
| `aster/browser_actions.py` | Exact reviewed HTTP(S)/search OS-browser handoff, without page reading |
| `aster/browser_public.py` | Explicit anonymous static source session, disposable-worker supervisor and CLI |
| `aster/public_worker.py` | Fixed bounded child for public transport, without browser/account state |
| `aster/apps.py`, `aster/app_adapters.py` | Read-only registrations and explicitly approved workspace exports |
| `aster/abilities.py`, `aster/ability_workshop.py` | Inert source proposals and separately reviewed bounded text-recipe tools |
| `aster/private_memory.py`, `aster/reference_library.py` | Local memory controls and cited approved-folder snapshots |
| `aster/communications.py`, `aster/media_workshop.py` | Local imported inbox/drafts and reversible PCM WAV copies |
| `aster/resources.py`, `aster/support.py` | Existing-queue admission budgets and fixed CLI/desktop operation registry |
| `aster/voice.py`, `assets/voices/` | Pinned prerecorded audition and integrity inspection |
| `aster/startup.py`, `launch_aster.py`, `aster/lifecycle.py` | Opt-in startup and lifecycle reliability source |
| `aster/memory_pressure.py`, `aster/system_control.py`, `aster/app_relief.py` | Candidate resource policy and disabled external-app planning boundary |
| `remote-companion/` | Separate web/relay/workstation-bridge prototype |
| `android-companion/` | Separate Android offline UI/protocol source |
| `tests/` | Unit, integration, process-crash, platform, and UI smoke tests |
| `scripts/check_companions.py` | Companion protocol/source checks using existing tools |
| `.github/workflows/tests.yml` | Windows/Linux verification matrix |
| `docs/` | Detailed contracts, limitations, and chronological validation records |

## Validation and acceptance milestones

### Run the available checks

```sh
python -m unittest discover -s tests -v
python -m compileall -q aster tests scripts
python scripts/check_companions.py
```

Companion checks require existing Python, Node.js, and JDK 17+; they install nothing and do not build an Android APK. The native Tk smoke needs a display. A Linux headless skip is not a visual pass; Windows qualification treats a missing required Tk window as a failure.

### Last recorded desktop milestone

The implementation commit `32f1442074e903c78edd859913a33b941305ba6d` passed [Windows and Linux CI](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37229004947):

- Windows: 157 collected, 152 executed successfully, five explicit platform/POSIX skips. The actual Tk UI smoke, socket-denied outage test, and all 20 native Windows file cases ran.
- Linux/headless: 136 of 157 executed successfully, with 20 Windows-native cases and one display test skipped.
- Both platforms: compilation, 10 relay/bridge Python tests, five Node tests, and 1,055 Java protocol assertions passed.
- A separate cloud graphical-session run passed all 37 dashboard tests, with manual UI checks and layout review recorded in [validation history](docs/VALIDATION.md).

These numbers belong to that exact milestone. New startup/RAM source must receive its own final review and checks; neither an older green run nor this README proves an updated branch head passed. The validation record retains earlier failures and corrections instead of replacing them with a blanket “all works.”

### Startup and resource milestone

Commit `ea2f0168bd6b88de38f4cecf7210877478a81869` passed
[Windows and Linux CI](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37231361624):

- Windows: 237 collected, 229 executed successfully, eight explicit platform skips. Real Windows RAM counters, command-line parsing, alias refusal and the updated native Tk memory/recovery flow ran.
- Linux: 213 of 237 executed successfully, with 24 explicit platform/display skips.
- Both: compilation and the existing 10 Python companion tests, five Node tests and 1,055 Java assertions passed.
- Startup registration tests use fake registry backends; no real startup setting was installed.
- The first failed Windows fixture run is preserved in the validation record. The fix changed only owned test-path normalization, without relaxing runtime guards.
- Fresh manual cloud UI testing for this increment was blocked; no new manual visual pass is claimed.

Permanent [test-result receipts and history](docs/TEST_RESULTS.md) retain source pins, commands, outcomes, skips, links and limitations. Missing historical raw logs are marked unavailable rather than reconstructed.

Tests establish software mechanics within their scope. They do not establish NewBrain intelligence, semantic learning, ordinary conversation, subjective feelings, safe physical designs, or the usability of unrun device flows. The user's own computer has not been accessed or qualified by these cloud/CI results.

### Acceptance path

1. **Local shell foundation:** preserve identity and explicit history; safely manage bounded files; recover interrupted operations; keep jobs finite and reviewable. Implemented with recorded platform tests.
2. **Desktop and research snapshots:** verify repeated clicks, dismissed confirmations, restart, exact project/hash scope, and offline use. Implemented with the recorded desktop milestone.
3. **Startup and resource reliability:** qualify opt-in sign-in behavior, clean/unclean lifecycle, repeated-failure backoff, RAM evidence freshness, hysteresis, and job deferral on the exact candidate and intended Windows environment. Native automated checks passed for the recorded source; actual owner installation and sign-in remain unperformed. External-app closure remains excluded.
4. **Qualified NewBrain integration:** demonstrate real generation and separately measured learning/recall, identity isolation, cancellation, restart, failure behavior, and no fallback. Not complete.
5. **Live local voice:** verify authorized STT/TTS, the chosen original voice, interruptions, latency, privacy, resources, and offline behavior. Not complete.
6. **Live research/app tools:** implement explicit named APIs and exact project grants, provenance, cancellation, output receipts, and safe write boundaries. Discovery and snapshots are only the starting point.
7. **Secure companion use:** approve hosting/enrollment, harden transport and retention, test actual phone/laptop behavior, and qualify reconnect, revocation, background limitations, and any voice path. Not complete.
8. **Approved ability execution and physical-tool integration:** add isolated execution, measured tests, capability enforcement, rollback, and separate CAD/hardware validation. The current bounded text-recipe interpreter satisfies only a narrow local subset; general code execution and physical-tool qualification remain unavailable.

## Development principles and costs

Contributions should preserve clear status reporting, original Aster identity, no-fallback NewBrain reasoning, bounded permissions, exact provenance, regression tests, and honest failures. Prefer a small demonstrated capability to a broad claim supported only by a mock. Do not weaken a file boundary or substitute fake success to make a test pass.

The core shell and current companion prototypes use no paid runtime dependency. That does not guarantee zero total cost: hardware, electricity, network service, hosting, storage, voice computation, or transport may have costs. A free hosting tier can be evaluated later, subject to current quotas and the owner's approval; no paid plan, public deployment, or universally free voice service is promised by this repository.

Project licensing remains pending the owner's choice; this README does not grant a new license. Preserve third-party license and provenance information for any future adopted source, assets, models, or dependencies. An accessible repository or free download does not automatically mean unrestricted reuse.

Aster should grow through understandable, reversible, evidence-backed steps. Her ambitions can be large; the claims about what she can do today should remain precise.

An optional [synthetic temporal vision lab](docs/TEMPORAL_VISION_EXPERIMENT.md)
compares bounded deterministic tracking, occlusion recovery and honest ambiguous
identity handling. Existing NewBrain shape/color checkpoints remain frozen and
separate. [Retained results](test-results/temporal-vision/README.md) include failures;
this does not enable live vision or movie understanding in the application.
