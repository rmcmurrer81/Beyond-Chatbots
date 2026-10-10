# Kira Labs IdeaForge

IdeaForge turns a natural-language idea into an engineering research project.

## October 2: shared Windows hands-free chat

Hands-free now uses the same generic female Windows speech engine as the other
Kira research apps. It starts **off**, pauses recognition for each chat request
and spoken answer, suppresses stale voice playback after Stop, and closes cooperatively.
No Whisper model, GPU speech workload, audio recording file or cloud key is
needed for this path. The former `ai/voice.py` implementation is retained as
legacy source and is no longer imported by the app.

See [voice setup and controls](ai/HANDS_FREE.md). Speech recognition accuracy,
voice quality and engineering answer quality remain separate checks.

You should be able to say something as simple as:

> "I just watched Avengers and I want to build my own real working Iron Man-style suit."

IdeaForge's job is to translate the idea into engineering questions, research areas, subsystems, candidate technologies, missing capabilities, parts, tools, suppliers, blueprints and future research to monitor.

## First foundation

Version 0.1 starts with the conversation layer:

- local Ollama `qwen3.5:9b` chat;
- normal typed chat;
- **hands-free microphone conversation**;
- local **female Windows voice** for spoken replies;
- microphone pauses while the AI speaks to prevent feedback;
- optional wake phrase support;
- project creation from natural conversation;
- persistent project folders.

The shared speech path uses installed Windows recognition and speech components.

## Windows install

1. Install Python 3.11+.
2. Install Ollama and make sure `qwen3.5:9b` is available.
3. Download/clone this repository.
4. Double-click `install_windows.bat`.
5. Double-click `IdeaForge.bat`.

Windows voice setup is a separate explicit build described in `ai/HANDS_FREE.md`.
Starting hands-free does not download a model or compile the speech helper.

## Hands-free mode

Open IdeaForge and click **Start Hands-Free**.

The cycle is:

```text
listen
  ↓
detect speech
  ↓
local speech-to-text
  ↓
Qwen 3.5 IdeaForge response
  ↓
female local TTS voice
  ↓
resume listening
```

The microphone is suspended while speech synthesis is playing.

The shared engine selects an installed en-US female voice, preferring Zira.
Optional wake-phrase settings remain in `ai/config.json`; other legacy
speech-to-text/voice settings there apply to the preserved old implementation.
**Stop** disables hands-free. **Mute AI voice** keeps recognition active after
a reply while suppressing spoken answers. Typed chat remains available.

## Project behavior

When the user describes a new invention, IdeaForge creates a project directory under:

`projects/<project-name>/`

The initial project stores:

- original idea;
- interpreted engineering goals;
- subsystem list;
- feasibility notes;
- research questions;
- project conversation log.

Later versions will add the full research, blueprint, BOM, supplier, price and knowledge systems similar to Humanoid Researcher but generalized to arbitrary inventions.

## Safety / engineering truth

IdeaForge should never invent missing dimensions, part ratings, fastener sizes, prices, test results or engineering capabilities. Fictional inspiration is treated as a **goal description**, not proof that a technology already exists.


## Equipment memory and 3D printing

IdeaForge now keeps a persistent equipment inventory under `inventory/`.

You can simply say:

> "I have a Bambu Lab P1S 3D printer."

IdeaForge records the equipment and, when an exact 3D-printer model is provided, attempts to research supported specifications such as build volume and useful capabilities. It can also optionally read the Humanoid Researcher equipment inventory when both repositories are installed side-by-side.

Open the inventory with **My Equipment** or `MyEquipment.bat`.

### Printable prototypes

IdeaForge has a fabrication layer under `fabrication/`.

For supported parametric parts, it can create editable OpenSCAD files and automatically export STL files when OpenSCAD is installed. The first supported production path is a parametric plastic enclosure/case.

Before generating geometry, IdeaForge creates a prototype plan. Missing dimensions remain **TBD** rather than being invented.

The STL validator checks:

- mesh dimensions;
- watertightness;
- estimated volume when available;
- whether the model fits the stored 3D-printer build volume.

More complex geometry is marked `custom_cad` until a proper CAD generator is available.

## University, laboratory and web research

Each new invention receives a small initial research pass automatically.

The research engine can gather:

- general web sources;
- appearance/reference-image links;
- arXiv papers;
- OpenAlex scholarly works;
- universities and institutions associated with recent work.

A deeper pass can be triggered by saying **"research this project"**, **"search universities"**, or **"search labs"**, or by clicking **Research Project**.

Results are stored inside the current project under `research/`, including a source-grounded `RESEARCH_BRIEF.md`.

## Virtual simulation

IdeaForge creates a staged simulation plan instead of pretending that one simulator proves an invention works.

The framework distinguishes:

- STL/3D-printer fit and mesh checks;
- rigid-body simulation;
- kinematics;
- structural analysis;
- thermal/power analysis;
- optics/VR analysis;
- electronics;
- human factors.

PyBullet is optional and can be installed with `InstallSimulationTools.bat`.

Say **"simulate this"** or click **Simulation Plan**.

## Persistent project memory

IdeaForge remembers explicit engineering details you give it during a project, such as:

- dimensions;
- material choices;
- required components;
- test constraints;
- preferences;
- budget-related constraints.

The most recently used project and recent conversation are reloaded the next time IdeaForge starts.

This allows a later request such as:

> "Make the plastic case STL now."

to use dimensions or constraints you supplied earlier, rather than returning to the original one-sentence idea.


## Troubleshooting with photos and screenshots

IdeaForge can now troubleshoot something you already built or tested.

You can say things such as:

- "the motor jitters but does not turn"
- "this hinge keeps binding"
- "the 3D print is warping"
- "the STL will not slice"
- "the program shows this error"
- "this part does not fit"

Then optionally attach a photo or screenshot.

The main IdeaForge window now includes:

- **Attach Image**
- **Paste Screenshot**
- **Clear**

For screenshots, you can use Windows Snipping Tool, copy the capture, then click **Paste Screenshot**.

When an image is supplied, IdeaForge uses the optional local `qwen3-vl:8b` vision model to extract visible evidence such as:

- error messages and codes;
- labels and model numbers;
- damaged or misaligned areas;
- print defects;
- UI state;
- wiring/connector markings;
- visible dimensions or part IDs.

It then combines that with:

- the current project files;
- remembered project measurements and constraints;
- fabrication and simulation outputs;
- your saved equipment;
- previous troubleshooting attempts;
- fresh web search results.

The diagnostic report separates:

1. observed facts;
2. likely causes;
3. ordered diagnostic checks;
4. possible fixes;
5. stop conditions;
6. useful source links.

Troubleshooting incidents are saved under:

`projects/<project>/troubleshooting/`

Follow-up statements such as **"that didn't work"**, **"same error"**, or **"that fixed it"** are retained in the incident history.

Run `InstallVisionModel.bat` once if `qwen3-vl:8b` is not already installed. Text-only troubleshooting works without the vision model.


## Multi-project workspace and live reference gallery

IdeaForge now supports multiple projects at the same time.

The main window has three panes:

- **Projects** — project list plus open/closed and research status.
- **Conversation** — typed/hands-free chat.
- **Project Details & References** — live project summary, variants, selected target and reference images.

You can say:

- `show my projects`
- `close this project`
- `open my R2-D2 project`
- `start another project`
- `research this project`
- `use variant 2`
- `use image 4`

Closing a project only closes it from the current workspace. Queued/running research continues in the background while IdeaForge is running. If the app is closed during a research job, its state is retained and the job is queued again next time IdeaForge starts.

### Character and prop builds

For visually specific builds such as convention robots, props, costumes or fictional devices, IdeaForge can store a `visual_reference_target` and collect a local image-reference gallery.

If search metadata suggests multiple versions, IdeaForge creates a variant list and shows it on the right side of the app. You can choose a variant by speaking/typing or choose a specific displayed image with **Use this**.

The selected target is saved in `design/selected_reference.json`, and prototype planning reads that selection so later fabrication work stays tied to the chosen design.

See `docs/MULTI_PROJECT_WORKSPACE.md`.


## Continuous research watch and useful-discovery notifications

IdeaForge now treats invention research as an ongoing watch while the application is running.

Each project has a persistent technology horizon. For a project such as:

> "I want to build a real holodeck."

IdeaForge can expand the idea into real enabling-technology searches. The included holodeck-like profile seeds topics such as:

- volumetric displays;
- light-field and holographic display research;
- projection mapping;
- room-scale AR/VR;
- tracking;
- spatial audio;
- ultrasonic/mid-air haptics;
- acoustic levitation;
- plasma/voxel display research;
- optical trapping/light-matter research;
- shape-changing interfaces;
- robotic encounter haptics;
- omnidirectional locomotion;
- AI-driven virtual characters.

A fictional idea such as **hard light** remains labeled fictional/undemonstrated as portrayed. IdeaForge instead watches real technologies that might approximate parts of the desired experience.

### What can be built now vs experimental vs missing

After each research pass, IdeaForge updates:

- `research/technology_horizon.json`
- `design/virtual_concepts.json`
- `design/VIRTUAL_BUILD.md`

The virtual-build report keeps separate:

1. a buildable-now concept;
2. experimental upgrades worth watching;
3. speculative/undemonstrated capabilities;
4. next virtual tests.

### Recurring watch

By default, watched projects are checked again every **60 minutes** while IdeaForge is open. Change the interval in:

`research_engine/watch_config.json`

Closing a project from the workspace does **not** stop its watch.

You can say:

- `stop watching this project`
- `keep researching this project`
- `pause background research`
- `resume background research`

### Useful-discovery detection

On later research passes, IdeaForge compares new results with the previous project research.

A result only becomes a discovery notification when the local AI judges that it materially helps the project and exceeds the configured usefulness threshold.

Useful discoveries are saved under:

`research/discoveries/`

and summarized in:

`research/LATEST_DISCOVERIES.md`

The main IdeaForge window shows:

- a **New** discovery count beside the project;
- an in-app discovery banner;
- an audible app bell;
- an **Open Project** button.

This can notify you about a closed project's useful discovery while you are working on another invention.

The recurring watcher stops when IdeaForge closes. Queued/running state is preserved so interrupted work can resume on the next launch.

## Grounded ordinary chat

Ordinary project chat now includes a bounded snapshot of saved engineering facts,
the actual selected visual reference, shared owned-equipment inventory, and the
plan's open questions/unknowns, even after reopening a project. Current keyed
facts supersede older revisions; extraction is still model-assisted, so use the
same fact key for a correction and verify safety-critical measurements. Missing
values remain TBD. Plan questions and extracted facts are not independently
verified measurements.

A local SQLite FTS5 cache (`chat_evidence.sqlite3` inside each project) searches
saved web snippets/paper abstracts and research briefs. Search and citation lookup
both require the current project ID, never its display title. Projects without
an ID use their resolved folder identity. Shared equipment is explicitly labeled;
project-tagged inventory entries are filtered to the current project.

Answers can cite an exact `[IF-…]` identifier and the original source URL. For
local inspection, `core.chat_context.resolve_citation(project_root, citation)`
returns its exact saved passage, project ID, source URL, source-file JSON pointer
or Markdown path, and character range. Generated briefs/discovery summaries carry
`generated_summary_not_primary_evidence`; search-result excerpts carry
`untrusted_source_excerpt`. Source material is data, not instructions. These
boundaries reduce injection risk but do not make a language model immune to
malicious source text.

The cache is regenerated transactionally from current allowlisted source files
before ordinary chat, removing replaced/deleted passages. Unchanged excerpts have
stable IDs across restarts; citations to removed/revised excerpts no longer
resolve. JSON source files remain authoritative. No documents are downloaded,
no embeddings/API service is added, and no new package is required. Python's
SQLite must support FTS5; otherwise chat retains current facts and reports that
evidence retrieval is unavailable.

Bounds: at most six 900-character evidence passages, 18,000 characters of JSON
context, 24 literal search terms, 1,000 indexed passages, 2,048-character source
URLs, and 4 MB per source file. Overlong/unsafe URLs are omitted, never shortened
into invented addresses; the local source locator remains available. Long state sections
explicitly report truncation/omissions. Very large or malformed sources disable
retrieval rather than silently supplying stale evidence. Retrieval is synchronous
and reindexes current files each turn; large project libraries may need an
incremental index later. This is lexical search over saved snippets, not full-paper
reading, source verification, engineering validation, or simulation.

Offline regression checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```

The context tests use synthetic projects and mocked model calls, including
identical titles with contradictory facts, 20 turns/questions, restart
persistence, project filtering before the result limit, citation resolution,
keyed fact replacement, missing/TBD values, literal query escaping, and explicit
untrusted/generated evidence labels. They do not prove live-model injection
resistance or answer quality.


## 3D assembly workspace

Use **3D Assembly Workspace** to inspect explicit measured parts, edit custom idea requirements, run bounded geometric checks, and compare durable candidate revisions. See [the workspace guide](docs/3D_WORKSPACE.md) for setup, example assemblies, research scope, and the limits of this first slice. This is not a full CAD or physics-validation system.


## October 6: evidence verification

The engineering pilot now checks the exact exported STL and its manifest against
the reviewed idealized cuboid before reporting CAD passed. No silent geometry
repair or inferred units. See [export verification](docs/EXPORT_VERIFICATION.md).

Discovery assessment now preserves source/query coverage, stable evidence
versions and retryable pending work. Model selections are bound to saved source
IDs. See [discovery selection](docs/DISCOVERY_SELECTION.md).

[Verification receipt](docs/test-receipts/2026-10-06-evidence-fixes.json).
These results do not qualify live model answers, Windows, manufacturing or real hardware.

## Opt-in Aster text-provider preparation

Standalone remains the default. `python -m ai.provider` shows the selection;
`python -m ai.provider --provider aster` explicitly selects the prepared Aster
boundary. Aster currently reports **unavailable**, with no hidden Ollama fallback
and no image-model access. Return with `--provider standalone`.
See [provider selection and offline verification](docs/AI_PROVIDER.md) for the
operation, cancellation, background recovery, and capability limits.
