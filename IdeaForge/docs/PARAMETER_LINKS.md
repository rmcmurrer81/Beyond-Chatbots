# Reviewed PDF passage links to design parameters

This increment adds local review annotations over the existing workspace scene history. It does not create a replacement design history, change CAD, accept a BOM, certify dimensions, or run a model. A human chooses an existing design revision and a specific dimensional/angular parameter, reviews an exact native PDF quote, and explicitly confirms the link.

## Existing evidence is reused

- Scene revision IDs, parent history, undo-by-new-revision, and canonical scene hashes remain defined by workspace3d.store.Store and workspace3d.model.digest. Store fingerprints also include reason, sources and parent; they are not scene hashes.
- PDF bytes, SHA-256, version IDs, exact native object strings, pages and object bounding boxes remain defined by core.pdf_evidence. A citation resolves preserved historical bytes even after replacement.
- Database and standard SQLite journal/WAL/SHM sidecar paths refuse symlinks, Windows reparse points and multiple hard links before opening. New annotations and immutable link-bound receipts live separately in workspace3d/parameter_links.sqlite3 under the selected project. Project ID and canonical root binding prevent a copied ledger from being used in a different project/location.
- The existing scene file, revision record, latest/input/accepted pointers are never written by annotation methods.

The native PDF coordinate convention is "PDF user space; left,bottom,right,top"; a box covers the whole native text object, not an inferred glyph-level numeric box. Only the selected string offset identifies the numeric occurrence within that object. This feature does not promise OCR, table semantics, reading order, visibility, or that a quoted dimension is true.

## Explicit review contract

ParameterLinks(project_root).create(request) accepts exactly:

- schema: ideaforge.reviewed-parameter-link.v1
- project_id, exact current revision, and existing canonical scene_hash
- parameter: exact part_id, supported field, and index
- source: exact resolver fields project_id, source_id, version_id, citation, source_sha256, page, bbox, object_index, passage, coordinate_system
- selection: exact start Unicode string index, quote, numeric_text and unit
- review: confirmed true, nonempty reviewer, UTC reviewed_at with explicit offset, and nonempty rationale

Review is a locally recorded operator assertion, not an authenticated identity service. Programmatic callers are responsible for obtaining real user confirmation; setting the flag automatically is not a review workflow.

Supported parameters are existing part vectors size_mm, position_mm, rotation_deg with indices 0..2, and existing joint scalar fields joint.min_deg, joint.max_deg, joint.angle_deg with index null. Units are exactly mm or deg as dictated by the field. No conversion occurs. A quoted plain decimal value must equal the existing parameter using decimal comparison. Unsupported fields, booleans, missing units, value mismatches, substring matches inside larger numbers, powered/compound units, missing evidence and unknown fields are refused.

For example, an existing 120 mm dimension can be linked to the exact selected string "120 mm" in its source object. "12 cm" is a unit mismatch; "120 mm/s", "120 mm²", or "120 mm s^-1" is an unsupported compound/powered unit. Creating a link never changes a 130 mm parameter to match a 120 mm quote.

The source hash, version, citation, page, full object text, box, numeric spelling, unit and existing parameter value are preserved together in an immutable record with a SHA-256. Repeated identical confirmation is idempotent while that exact link is active. Changed reviews or withdrawn links create distinct records.

## Current, stale, unknown and withdrawn evidence

inspect(link_id) reevaluates the preserved source citation and scene revision:

- current: the exact design revision remains latest, its hash and parameter match, and the exact source version is active and matches.
- stale: a new source version replaced the reviewed version or the latest design revision changed. A new revision with identical geometry still differs from the reviewed revision.
- unknown: required evidence is missing, malformed, inconsistent, or the source snapshot is busy. Unknown does not become a successful validation.
- withdrawn: a user reversed or withdrew the association. Immutable original records remain available.

Historical source bytes and quoted strings stay preserved. Re-importing identical PDF bytes with a new version still makes the old link stale. Restoring geometry with the existing Store creates a new revision; it does not silently reactivate old links. Changes to the original external PDF file before an explicit re-import cannot be detected by preserved snapshots.

Create holds the existing PDF import lock and a short existing Store transaction while committing its separate annotation. Inspection holds a PDF import lock and a scene read transaction across the source/scene snapshot. These coordinate cooperating local writers; they are not protection against a hostile process replacing files between operating-system calls.

withdraw(link_id, review) adds a reversible state event. undo(expected_event, review) reverses only the newest ledger event, refuses an outdated event ID, and never erases original evidence. Undo can restore an association's active state; evidence is still reevaluated and remains stale/unknown if its source or revision changed.

## Link-bound test receipts

attach_test_receipt(link_id, receipt) stores an immutable local ideaforge.parameter-link-test.v1 receipt. Exact fields are schema, id, project_id, revision, scene_hash, source_sha256, link_sha256, status, command, observations, run_at, review. Scope and hashes must match the link. Status is passed, failed or unrun; unrun requires run_at null. A passed/failed receipt must contain a UTC execution timestamp. The API records a caller's reviewed evidence; it does not execute or independently verify the command.

Returned tests retain their original receipt status and separately report evidence_status. A later source replacement or scene revision change makes link-bound test evidence stale without rewriting a historical pass/fail result. These receipts do not replace the Store's scene checks and do not make source dimensions certified.

## Local usage and limits

The additive API is workspace3d.parameter_links.ParameterLinks. The local CLI is:

python -m workspace3d.parameter_links --project PATH create request.json

Other subcommands are inspect LINK_ID, withdraw request.json, undo request.json, and receipt request.json. Withdraw/undo request files contain only the respective link/event ID and review object; receipt requests contain only link_id and receipt. JSON input is strict UTF-8; duplicate, unknown and nonfinite fields are rejected. No scene GUI button is included in this increment. The API/CLI records a confirmation produced by a user-facing caller; it does not itself authenticate a reviewer.

Limits: 256 links, 1024 state events, 512 receipts, 24,000 bytes per annotation/receipt JSON and a 16,000,000-byte ledger check before opening. SQLite lock timeout is two seconds for the annotation ledger; the existing Store timeout remains ten seconds. These are bounded-work/storage safeguards, not a measured elapsed-time or memory guarantee. No directory-wide scan, installation, native PDF extraction or model inference is performed by link creation/inspection. PDF retrieval retains its existing bounded source/character/deadline limits.

New records are kept out of existing chat/provider context. The module makes no network calls, sends no PDF to a third party, and introduces no new third-party dependency. Python standard library only is required for links; existing optional PDFium extraction requirements/licenses remain documented in PDF_EVIDENCE.md.

## Verification receipt

tests/test_parameter_links.py authors 40 focused methods, including known compatibility, exact boxes/text/value, unit and compound-unit mismatch, missing evidence, other-project/copy refusal, changed scene, same-byte source replacement, real child-process restart, reversible undo, receipt staleness, malformed persisted records, idempotence, budgets and absence from provider context. Native PDF imports in these tests use an explicitly synthetic storage report, so they test storage/link behavior and cannot prove native PDF extraction.

At source publication these tests and the outstanding prior 25 PDF methods remain UNRUN unless an actual execution receipt states otherwise. Source/test design review and GitHub hash readback are distinct from compilation, runtime, native extraction and end-to-end UI validation.


## Explicit local Aster metadata bundle

core.ideaforge_bundles.export_parameter_link(project_root, link_id, directory_name, producer_revision=...) prepares a freshly selected local metadata bundle through the shared app-agnostic core.research_bundle producer. export_reviewed_result accepts a selected photo-inventory metadata result with the supported ideaforge.reviewed-photo-inventory.v1 schema. Neither API transmits data, invokes Aster/provider, executes code/tests, or adopts a result.

Both adapters accept an explicit boolean test_only flag for provenance (default false); synthetic fixture calls must supply true. It does not claim tests ran. The versioned envelope is aster.research-bundle.v1 with recipient aster, app_id ideaforge, project_id, revision, artifacts, inputs and tests. Exact typed wrappers preserve app schema/status/provenance/result. Bound test receipts use aster.test-receipt.v1 and passed/failed/unrun separately. The consumer may hash-check included files; declared provenance and test status do not imply it reran anything or validated source claims.

Parameter exports omit the full native passage, original PDF filename, local root binding, reviewer and rationale. They retain the exact selected numeric quote and source hash/version/page/box plus scene/parameter binding. Original PDF bytes are excluded and pdf_source_verification is unavailable. Source SHA values inside app metadata describe preserved local evidence; the input entry's SHA instead hashes the ACTUAL included JSON summary bytes. The recipient cannot independently validate the original PDF, image, numeric extraction or human review from this metadata-only bundle.

Photo exports require original_image_bytes_in_bundle false and image_verification unavailable. Original image files, serials and private observations should remain excluded by the photo result producer. Included JSON result summaries are explicitly selected local metadata, not image verification by Aster.

The adapter temporarily stages a fresh selected JSON input summary under research/result_inputs, then the canonical producer reserves a fresh single portable directory name under the project root. Inputs/artifacts/receipts are bounded strict UTF-8 JSON/text; original binary PDF/image files are refused. Files and receipts have exact byte counts/SHA-256 and references. Paths exclude absolute/traversal/network/ADS/device/symlink/hardlink escapes and case collisions. Envelope and individual files are at most 256 KiB; total export files at most 1 MiB. Do not externally transmit private selected data; these APIs create local outputs only.

The canonical producer is shared verbatim with the other approved apps. It may leave a new incomplete export directory on an interrupted write; the manifest is written last and existing destinations are not overwritten. Owned staging summaries are removed after the canonical producer copies them, including after later validation failures. Changed or escaped staging paths are refused during cleanup. An abrupt process interruption may leave a staging file requiring manual recovery; no automatic broad cleanup runs. Private staging paths and default result-bundle directories are ignored by Git.

tests/test_ideaforge_bundles.py authors 12 focused local file/output methods, covering exact file/receipt hashes, unrun status, redaction, distinct included-input/source hashes, stale receipt meaning, no CAD/source mutation, metadata-only photos, other-project refusal and path/duplicate/field violations and distinct portable filenames for case-sensitive IDs. These remain UNRUN at source publication unless a later actual execution receipt states otherwise. Export-to-Aster consumer integration has not been executed here.
