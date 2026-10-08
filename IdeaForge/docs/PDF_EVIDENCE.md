# Local native PDF quotation citations

## Public-copy correction: troubleshooting can expose quotations

The application-wide privacy assertion in the original text below is incorrect.
The PDF import/retrieve/resolve CLI/API itself makes no provider call, and the
plain chat-context builder excludes the PDF store. Existing troubleshooting,
however, recursively reads project text/JSON files and may include saved
research/pdf_evidence/versions quotation records in a text-provider request.
Chat can invoke that troubleshooting route for a problem or attached image.
Do not import private PDFs into projects used with those model routes until a
reviewed exclusion is implemented. Use synthetic fixtures for this snapshot.
The runtime source is unchanged; no new privacy regression test was executed.
This correction supersedes the older never-inserted-into-provider-context
statement below. The historical source/test-design status is preserved.

This candidate adds deterministic local PDF import, token retrieval and citation
resolution. It does not change ordinary chat, provider routing, UI, design
selection, CAD generation, workflows or main. PDF bytes and extracted text are
never inserted into existing provider context. A loopback model endpoint may be
a proxy; loopback addressing does not establish offline processing.

Implementation and test sources were uploaded through the authorized GitHub
connector because the desktop executor could not start. Dependency installation,
compilation, fixture extraction, all runtime tests and performance measurements
were UNRUN when this candidate was prepared. Independent source review does not
establish working runtime behavior. See the receipt in docs/test-receipts.

## Use after a scoped local test window is agreed

From the repository checkout, install the optional wheel in the environment you
intend to test. Binary-only installation avoids accidental PDFium source builds:

    python -m pip install --only-binary=:all: -r requirements-pdf-evidence.txt

This command is an instruction, not a recorded installation. No private PDFs
should be uploaded to a model, document converter, public test corpus or this
repository. Use the self-authored fixtures for evaluation.

The project must already contain project.json. Import is explicit:

    python -m core.pdf_evidence --project projects/10000001 import C:/manuals/source.pdf --title "Actuator source"
    python -m core.pdf_evidence --project projects/10000001 retrieve "shaft voltage"
    python -m core.pdf_evidence --project projects/10000001 resolve IF-PDF-<citation-digest>

Replace a source by importing its new bytes with the source_id returned by the
earlier import:

    python -m core.pdf_evidence --project projects/10000001 import C:/manuals/source.pdf --source-id <source-id>

API equivalents are ingest_pdf(), retrieve_pdf() and resolve_pdf_citation().
Results are JSON quotations with provenance, not generated answers. Searches
use literal tokens and do not join separate native objects into phrases. A
statement split across PDF text objects may be missed or returned as fragments.

## Exactness and supported scope

Each accepted passage preserves the exact string returned by
PdfTextObj.extract(), using strict UTF-16 decoding, without trimming whitespace,
normalizing CRLF, rewriting ligatures, dehyphenating or converting numbers.
This is unaltered PDFium text-object extraction; it does not establish equality
with original encoded PDF strings or validate their Unicode mappings.

Each citation includes the preserved source SHA-256, one-based PDF page,
zero-based native object index, effective page box and object bounding box.
Boxes use PDF user-space coordinates as left,bottom,right,top. They encompass
the whole native text object; they do not isolate an individual number.
No pixel, glyph-perfect annotation or visibility proof is claimed.

The first implementation accepts only top-level, axis-aligned text objects on
unrotated pages with an explicit zero-origin MediaBox matching the effective
page box. It refuses Form XObjects, unverified inherited MediaBoxes, rotation,
shear/reflection, crop differences, partially clipped/outside text, Unicode
decoding or reported mapping errors, and over-budget input. These refusals are
deliberately narrow; many otherwise valid PDFs will be unsupported.

No OCR, page rendering, model inference, layout analysis, reading-order
reconstruction or table semantics run. Table headings, row/column associations
and units cannot be inferred from proximity. Every quotation states that table
relationships remain unsupported. The software does not reliably detect tables.
Image-only PDFs fail with an explicit no-native-text/unsupported status.
A mixed document records a support status for every page; pages without native
text remain uninterpreted and contribute no quotations. An empty page is not
automatically identified as a scan.

Extracted numbers are source claims only. Nothing in this feature writes
validated CAD dimensions, equipment specifications, project facts, BOM choices
or design promotions. A human must inspect the preserved page and evaluate
engineering claims separately.

## Persistence, scope and budgets

Local files are under research/pdf_evidence/ inside the selected project:

- sources/<sha256>.pdf retains byte-identical immutable source snapshots.
- versions/<version-id>.json retains exact strings, boxes, limits and backend metadata.
- manifest.json binds version records and source hashes to project identity and location.
- .import-lock excludes concurrent imports to the same store.

Restart verifies record, source and citation hashes. Source replacement changes
the active version while preserving historical source snapshots and citations.
Retrieval searches active versions only. Resolution can return an older preserved
citation with active=false; it must not be represented as current source evidence.
A copied store or moved project location fails its root binding; reimport explicitly
at the new location rather than silently adopting foreign evidence.

Defaults/hard maximums: 8,000,000 input bytes; 25 pages; 2,000 native objects per
page; 2,000 characters per text object; 100,000 extracted characters per document;
2,000,000 output/record bytes; 8 active sources; 32 retained versions;
64,000,000 retained source/record bytes. Source and version directories each
permit at most 32 entries, including orphan files. Root store enumeration permits
only its four known entries; interrupted staging/temporary files require manual
inspection before a new import. Streaming os.scandir enumeration checks the same import deadline and
stops when an entry cap is exceeded. Unsupported coordinate magnitudes above
1,000,000,000 user-space units fail explicitly. Import defaults to 10 seconds and permits
a maximum of 30 seconds. Retrieval defaults to 2 seconds, permits at most 5,
and returns at most 6 quotations for a query of at most 2,000 characters.

A dedicated subprocess owns native extraction. The parent enforces its hard
deadline and kills only that task-owned worker, with up to 2 seconds to confirm
shutdown. No project-process enumeration or unrelated process termination occurs.
Retrieval uses cooperative deadline checks around bounded local reads,
validation, passage iteration and sorting. Those checks do not interrupt a stuck
filesystem operation. No native memory ceiling, peak-memory measurement, file
read latency guarantee or sub-two-second performance claim has been established.

Only a successful bounded import atomically changes the active manifest.
Interrupted or failed writes can leave unreferenced source/version files while
preserving the old active manifest. Those files count toward storage and entry budgets. Unexpected interrupted
staging or temporary files fail closed until manually inspected.
A crash can leave .import-lock. Recovery/pruning is manual: inspect the import
and confirm its own worker is gone before removing only that project's stale
lock or unreferenced files. Do not remove another project's state or process.

## Test sources and honest execution status

    python -m unittest discover -s tests -p "test_pdf_evidence.py" -v

Storage/search tests use clearly labeled fake extraction reports. They cover
exact whitespace/numbers, twenty local question cases, restart in a fresh Python
process, old citations after replacement, source and record corruption, copied
project stores, identical filenames/titles, absence from ordinary provider
context, manifest failure recovery, query limits and task-owned worker timeout.
These tests have not run.

NativeBackendTests requires exactly pypdfium2 5.14.0; it is explicitly skipped
when that optional pinned backend is unavailable. Its real extraction test
generates two self-authored annotated native PDFs using only stdlib, with ten
questions per document. It compares exact returned strings, source SHA-256,
page/object identity, citation resolution and object boxes inside authored
annotation envelopes. A separately generated image-only PDF tests the scanned
negative. Rotation, crop, Form XObjects and page-limit refusals are additional
native cases. These native tests have not run. Skip results must be reported
separately from passes.

The fixture generator and its synthetic data are dedicated to CC0-1.0 by the
contributor. No private or externally authored PDF has been used.

Additional required QA before relying on the feature: inspect the generated PDFs
and the source boxes visually; exercise malformed/broken-font native PDFs,
Unicode outside the BMP, split objects, multiple columns and ambiguous tables;
check object/character/time limits against real adversarial fixtures; measure
cold/warm timings, installed package footprint and peak worker memory. Do not
claim these measurements from package wheel sizes or source inspection.

## Dependency evaluation and licensing

pypdfium2 5.14.0 is optional and pinned. Its official package source declares no
mandatory Python runtime dependencies beyond Python and bundled PDFium.
Text-object extraction does not require optional Pillow/NumPy converters.
The published Windows x64 wheel is 3,947,280 bytes; actual dependency closure,
installed footprint, import behavior and this feature's runtime remain unverified.

pypdfium2 code is Apache-2.0 OR BSD-3-Clause. Its documentation/examples are
CC-BY-4.0. Bundled PDFium has a separate BSD-style license and third-party
dependency notices. The installed wheel's licenses must remain with any binary
redistribution. This repository does not vendor PDFium binaries or upstream code.

The requested Docling 2.135.0 candidate was reviewed first. Its MIT
NativePdfPipeline is model-free and preserves text cells with provenance boxes,
but promises neither reading order nor table semantics. Plain docling==2.135.0
pulls docling-slim[standard], including model/OCR extras. A source-level lighter
candidate is docling-slim[convert-core,format-pdf-docling]==2.135.0, with nine
base direct requirements plus numpy/Pillow/rtree/scipy and docling-parse.
Its actual minimal resolved closure and working import path were not tested.
No Docling backend is implemented or installed here.

Primary source references:

- https://github.com/pypdfium2-team/pypdfium2/releases/tag/5.14.0
- https://github.com/pypdfium2-team/pypdfium2/blob/5.14.0/src/pypdfium2/_helpers/pageobjects.py
- https://github.com/pypdfium2-team/pypdfium2/blob/5.14.0/src/pypdfium2/_helpers/textpage.py
- https://github.com/pypdfium2-team/pypdfium2/blob/5.14.0/src/pypdfium2/_helpers/page.py
- https://github.com/pypdfium2-team/pypdfium2/blob/5.14.0/README.md#licensing
- https://github.com/docling-project/docling/blob/v2.135.0/pyproject.toml
- https://github.com/docling-project/docling/blob/v2.135.0/packages/docling/pyproject.toml
- https://github.com/docling-project/docling/blob/v2.135.0/docling/pipeline/native_pdf_pipeline.py
