# IdeaForge — conversational invention workspace

IdeaForge is Robert McMurrer's experimental workspace for developing an invention through conversation, keeping its project context, researching how it might be built, and turning reviewed requirements into prototype and simulation work. It aims to keep the idea, equipment, references, decisions and troubleshooting history together so each session can continue from the project.

This public copy is for the October 10, 2026 Beyond Chatbots presentation. It is a **source snapshot, not a qualified Windows release or a working NewBrain integration**. No program, model, installation, test or prototype was executed to prepare this copy.

## Which version is here

The selected coherent source is IdeaForge branch **dot/2026-10-08-local-pdf-citations**, commit **2834b24ac9ace82f8d8087b8058473c58f057985**, tree **93c53e0b87bf62e5c4bba3523edb38ea757499bd**. It descends from **6ade05db3ec72417f2e84d04347e4277514ee5ac**, including the earlier workspace/provider work, and is six commits ahead of the observed private main **ab021755cf49575fa1765b8c94e4b3898f0c1372**, with none behind. It is not merged into that main branch. No files from separate branches were overlaid.

The original IdeaForge repository remains private. This copy includes all selected generic runtime code, tests, configuration and synthetic examples. Three upstream files are omitted and four documentation/receipt files have disclosed public-copy changes; [snapshot contents](SNAPSHOT-CONTENTS.md) describes every change. [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json) records original blobs and exact public output hashes.

## What the source currently implements

| Area | Implementation in this source | Boundary |
| --- | --- | --- |
| Conversation and projects | A Tkinter desktop UI; model-assisted project creation/chat; conversation records, extracted facts and project status. Projects use random eight-digit identifiers under projects/. | A configured external model is needed for model-assisted operations. Stored records and extracted facts are not guaranteed to be correct or complete. |
| Equipment context | An empty generic inventory seed, a local equipment manager and optional imports from configured sibling HumanoidResearcher inventories. | No personal equipment data is included. The application can read actual configured inventories when run; review those settings first. |
| References and research | Web, image, OpenAlex and arXiv discovery; evidence/reference selection; bounded lexical SQLite FTS5 snippets with citation identifiers and locators for chat context. | Retrieved/model-assessed information still needs review. This is not automatic verification of a paper or an engineering claim. |
| Background discovery | Hourly project watches while the app is open, stored discoveries, assessment status, and model-assisted virtual-build/proposal updates. | Interrupted queued/running research is marked INTERRUPTED and needs explicit Research after restart. The chat command to pause background research pauses the current project's watch. |
| Troubleshooting | Project context, local notes, retrieved references and optional image analysis feed hypotheses and proposed diagnostic checks. | A proposed cause or fix is not a confirmed diagnosis; actual results need to be recorded and reviewed. |
| Prototype planning | Model-assisted plans, explicit enclosure inputs, prototype records and export checks. | Required enclosure dimensions must be known. Some derived defaults exist: lid thickness may use wall thickness and clearance may default to 0.3 mm. Review every value before fabrication. |
| 3D workspace | Explicit box/cylinder assemblies in millimetres, candidate revisions, manual acceptance/revert, a viewer, approximate AABB/printer-fit checks and a nine-sample kinematic sweep. | These geometric checks are not full dynamics, structural analysis, collision proof or validated real hardware. |
| Simulation work | Model-assisted plans and a separate optional fixed-function two-link CAD/dynamics pilot using CadQuery, MuJoCo and SciPy. | A synthetic two-link example cannot establish that an entire invention is buildable, safe or effective. |
| New local PDF citations | Preserved source bytes/hashes, native text-object quotations, page/object boxes, project-bound immutable versions, local retrieval and citation resolution. | This is a local CLI/API addition. Plain chat-context retrieval excludes its store, but troubleshooting can read saved quotation JSON and send it to the configured model. Its new runtime tests and installation are unrun. |

Each project's research_watch_enabled state defaults to true; research_engine/watch_config.json sets the 60-minute interval and enables auto_virtual_build. Its watch_enabled_by_default flag is ignored by this implementation. Candidate review and manual design acceptance exist, but this is not a universally human-approved change workflow. Examine project updates and artifacts before accepting or using them.

Older notes, including the auto-resume sentence in watch_config.json, may describe earlier intentions. The current interrupted-work behavior and [provider documentation](docs/AI_PROVIDER.md) take precedence. Historical receipts describe earlier exact scopes; they are not runtime certification of this copied snapshot.

## How it is supposed to work

Start with an idea and its unknowns. Keep measurements, decisions, constraints and available equipment attached to the project. Find and retain reference evidence, compare possible approaches, then review a proposed plan rather than accepting generated confidence as proof. Use explicitly reviewed dimensions for CAD, inspect exported artifacts, and compare bounded simulations with measurements and appropriate controls.

The desired direction is background research that presents reviewable candidate changes; more capable engineering/buildability analysis; CAD/prototype workflows tied to evidence; and eventual coordination with Aster and a qualified NewBrain interface. Broad automatic CAD inference, trustworthy full-invention simulation and working NewBrain conversation remain goals.

## AI and speech configuration

**Standalone is the shipped selection** in ai_provider.json. ai/config.json names an external Ollama text model, **qwen3.5:9b**, at http://127.0.0.1:11434 with a 180-second timeout. Optional image troubleshooting names **qwen3-vl:8b**. No server, model weights, model availability, output quality or Windows resource fit is supplied or verified by this copy.

The opt-in Aster selector uses the included generic stdlib preparation contract/client package. Its production transport is explicitly unavailable. Selecting Aster does not create a live Aster/NewBrain backend, and does not silently fall back to the standalone model. The standalone vision specialist is disabled in Aster mode. The package contains no NewBrain core, trained state or private memories. Its exact generic-package provenance is retained in [the provider manifest](docs/ASTER_PROVIDER_VENDOR.json).

Hands-free is off by default. The implemented voice path uses installed Windows speech components and a separately built generic System.Speech helper. No personal voice, cloned voice, recording or speech-model weights are shipped. The helper may share a Windows-session speech engine with the other applications and writes its build under LocalAppData. See [hands-free instructions](ai/HANDS_FREE.md) and [voice backend details](VOICE-BACKEND.md). Configuration also retains older speech-model fields; those fields do not establish a qualified alternative backend.

## Data flow and user controls

Projects, conversation, extracted facts, local inventory and retrieval indexes are written to local files. Local storage and loopback addressing do not prove offline processing or privacy.

Project context and equipment can be sent to the configured text provider. Research may send derived project queries to web search, OpenAlex or arXiv. Optional vision sends supplied images to its configured provider. PDF import/retrieve/resolve themselves do not call a model, and the plain chat-context builder excludes the PDF store. However, existing troubleshooting recursively reads project text/JSON and may include saved PDF quotations in a model request, including when chat routes a problem or image to troubleshooting. This copy therefore has no application-wide PDF privacy exclusion. Do not import private PDFs into projects used with model/troubleshooting routes until a reviewed exclusion is implemented; use synthetic fixtures here.

Before launching, review ai/config.json, ai_provider.json, inventory/config.json and research_engine/watch_config.json. Set inventory/config.json's optional_imports to an empty array if you do not intend to read neighboring inventories. The watch_enabled_by_default configuration flag is not honored by this implementation: watching is controlled by each saved project's workspace_state.json research_watch_enabled value, which defaults to true. Set that project flag to false before launching, or use core.project_state.set_watch_enabled(project_root, False). Setting auto_virtual_build to false stops automatic virtual-build synthesis, not research. A pause command after launch does not cancel already queued/running work. Model-assisted new-project creation queues an initial research pass regardless of the watch flag; use the offline smoke below instead of GUI project creation when avoiding network work. These are user-side controls; the copied configuration remains unchanged.

Use explicit microphone enable/disable controls. Keep personal data, credentials, private projects and copyrighted reference files out of public feedback or source commits. Close the app before resetting a disposable project; remove only that project, not shared inventory or unrelated application state.

## Windows setup — source-checked, not executed here

From the Beyond-Chatbots checkout root, first enter **IdeaForge/** as shown below; run the remaining commands inside it so relative configuration/project paths resolve correctly. The source documents Python 3.11 or newer; Python 3.12 matches the historical static/test lane. The example below assumes Python 3.12 with Tkinter is already installed and available through the Windows launcher.

```powershell
cd .\IdeaForge
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Read provider selection; this is not a live model test.
.\.venv\Scripts\python.exe -m ai.provider

# Launch the Tkinter UI after reviewing configuration/data flows.
.\.venv\Scripts\python.exe ideaforge.py
```

Alternatively, install_windows.bat creates an environment using py -3 and IdeaForge.bat launches its pythonw.exe. The installer checks for the Python launcher but does not enforce the stated minimum minor version. It detects configured Ollama models; it does not install Ollama or download those weights. A successful dependency installation alone does not make chat operational.

Base dependency ranges are requests>=2.32,<3; numpy>=2.0,<3; feedparser>=6.0.11,<7; ddgs>=9,<10; beautifulsoup4>=4.12,<5; trimesh>=4.4,<5; Pillow>=10,<13. Review installed-package and external-model notices separately. There is no measured Windows RAM/GPU/disk minimum for this branch. Broad ranges are not a resolved dependency lock.

Provider selection commands, also unrun here:

```powershell
.\.venv\Scripts\python.exe -m ai.provider --provider aster
.\.venv\Scripts\python.exe -m ai.provider --provider standalone
```

These change ai_provider.json. Aster mode is expected to report unavailable without a real approved transport. Restore standalone if that is the provider you intended; its external server/model still must exist.

## Limited synthetic smoke instructions — UNRUN

This source-level smoke example creates ordinary local project records without a model, network query, microphone, CAD export or simulation. The function and its signature were checked against core/projects.py; the command was not executed.

```powershell
.\.venv\Scripts\python.exe -c "from core.projects import create_project; from core.project_state import set_watch_enabled; p=create_project('Synthetic demo', 'A pretend enclosure for documentation review only.', {'summary':'Synthetic, unvalidated example.'}); set_watch_enabled(p, False); print(p)"
```

Expected by source inspection: one printed projects/<random-eight-digit-ID> path containing project.json, a project README, workspace_state.json with watching disabled, and research/fabrication/simulation/procurement/design/troubleshooting subdirectories. This is an expected output shape, not a recorded result or proof of model functionality. The smoke does not start the GUI/research manager. Keep that watch disabled before any later GUI launch; explicit Research can still access the network. When finished, close the app and remove only the disposable folder identified by that printed path.

For PDF storage/search test instructions:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pdf_evidence.py" -v
```

Those 25 methods are authored but unrun. Storage tests use fake extraction reports. Three native methods require the exact optional backend and can be skipped when it is absent; skips must not be counted as native passes.

## Optional PDF CLI/API — source-only addition

Install the optional prebuilt wheel only if testing this feature:

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-pdf-evidence.txt
```

The requirement is pypdfium2==5.14.0. No native binary is vendored. Installation and extraction have not been run for this version. A project must already have project.json, and the global --project option must precede the subcommand.

Example command forms below are **unrun**; replace the project identifier and file path with your disposable synthetic inputs:

```powershell
.\.venv\Scripts\python.exe -m core.pdf_evidence --project ".\projects\<project-id>" import ".\your-synthetic.pdf" --title "Synthetic manual"
.\.venv\Scripts\python.exe -m core.pdf_evidence --project ".\projects\<project-id>" retrieve "shaft voltage" --limit 6
.\.venv\Scripts\python.exe -m core.pdf_evidence --project ".\projects\<project-id>" resolve "<citation-returned-by-retrieve>"
```

These produce deterministic local quotation/provenance JSON by design, not generated answers. Use the self-authored synthetic fixture generator in tests/pdf_fixtures.py rather than private manuals for qualification. [PDF documentation](docs/PDF_EVIDENCE.md) specifies replacement/history and refusal behavior.

Source caps include 8,000,000 input bytes, 25 pages, 100,000 extracted characters, 64,000,000 retained source/record bytes, eight active sources and 32 retained versions. Import defaults to 10 seconds with a 30-second maximum; retrieval defaults to two seconds with a five-second API maximum and six quotations. These code limits are not measured performance, a native memory ceiling or a guarantee that a blocked filesystem read can be interrupted.

The extractor accepts a narrow class of native, unrotated, axis-aligned text objects. Many valid PDFs are intentionally unsupported. **Scans/OCR, table semantics, reading-order reconstruction, general layout understanding and automatic validated CAD numbers are unsupported.** Numeric quotations remain source claims. Source boxes cover entire text objects, not a verified individual glyph/number. Review the preserved page yourself.

## Optional engineering pilot

The separate pilot pins cadquery==2.6.1, mujoco==3.3.7, scipy==1.16.2 and trimesh==4.12.2. It has a bounded subprocess and accepts a new output directory with --seconds between 1 and 120. Its fixed two-link example is synthetic.

[Engineering pilot instructions](docs/ENGINEERING_PILOT.md) describe a separate environment and invocation. Their several-gigabyte disk and 8-GiB RAM guidance is planning advice, not a measured Windows minimum. No optional package installation, native test, physical prototype or hardware qualification was performed for this copy.

## Evidence and present limitations

| Evidence | What it supports | What it does not support |
| --- | --- | --- |
| Historical provider-preparation receipt: 181 tests, 180 passed, one native Tk display skip on Linux | Earlier deterministic/injected routing, state and lifecycle checks within that recorded scope. | Live models, native Windows GUI/voice or this new PDF feature. The private raw log is omitted; the retained receipt is sanitized. |
| Two successful Actions runs at prior 6ade05d | Python compilation and JSON parsing only. | Unit tests, live model quality or current Windows operation. |
| Historical synthetic engineering receipts | Narrow saved two-link/CAD checks with synthetic inputs. | Whole-invention buildability, real actuator/printer validation or structural safety. |
| Current PDF candidate: 25 authored methods, zero run; zero commit-associated Actions | Source/test-design/documentation review and exact blob provenance. | Installation, compilation, native extraction, visual box QA, timings, memory or working ordinary-chat PDF integration. |
| This public copy | Independent source/privacy/rights/claims review and remote hash verification at publication. | A new runtime/test result. No local execution or paid service was used. |

Report adverse results and skipped/unrun work separately. Reliable engineering answers, automatic validated CAD, robust arbitrary-PDF handling, broad app coordination and a working NewBrain cognitive connection remain unfinished.

## Attribution and reuse

Robert McMurrer / Kira Labs. This public copy is provided for inspection and the presentation. No project-wide software or asset license was found or selected, and public visibility does not grant general redistribution, modification or commercial-use permission.

The contributor's existing CC0-1.0 declaration applies only to tests/pdf_fixtures.py and its synthetic data. Dependency/model/installed-voice rights are separate. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md), retained notices and the manifest. No personal voice or private NewBrain state is included.
