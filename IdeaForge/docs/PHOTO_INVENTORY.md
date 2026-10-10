# Reviewed local photo inventory

This increment is a local intake, human review and inventory ledger. It does not recognize objects. No qualified part-perception backend was observed. Existing ai/vision.py sends images to a configured HTTP model and does not establish backend locality or qualification; this workflow never imports or invokes it. There are no network calls, provider calls, OCR, model runs, native image decoding or dependency installations.

## Local workflow

Run from the application checkout. Store real photos and review history in a private, untracked folder outside the checkout, or in a photo_inventory/ folder whose ignore rule you have confirmed. The examples below use projects/PROJECT/photo_inventory/; verify that path is ignored before using real photographs. Arbitrary explicitly chosen --store paths are not automatically ignored. Never force-add original image snapshots or ledger files to Git.

```text
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT intake board-1 front.png back.png --reviewer Robert --same-item-confirmed
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT quantity board-1 1 --reviewer Robert --ownership owned
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT review board-1 reviewed-observations.json
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT list
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT result board-1
```

These are documented commands, not executed-test evidence. IDs are portable ASCII, 1–64 characters. Quantity is a reviewed positive integer; ownership is separately chosen as unknown, owned or borrowed. Quantity stays unknown until explicitly confirmed. Several views do not create several parts.

Example human-review file:

```json
{
  "reviewer": "Robert",
  "expected_subject": "module",
  "confirm_identity": true,
  "observations": [
    {
      "photo_sha256": "REPLACE_WITH_EXACT_INTAKE_SHA256",
      "subject": "module",
      "kind": "model_code",
      "visibility": "clear",
      "text": "P3767-0003"
    }
  ]
}
```

Use the original photo SHA256 returned by intake. Allowed observation kinds are model_code, label and port. Visibility is clear, blurred or missing. Subjects are module, carrier, developer_kit or unknown; the overall expected subject may also be assembly. These observations are human declarations, not pixel-verified transcription. Arbitrary labels and ports are kept locally for provenance but cannot establish an exact model.

A review is provisional until the expected component kind has one supported exact public-code match, identity confirmation is explicit and quantity is confirmed. Conflicting exact codes for the same component kind, or assigning a carrier code to a module, remain conflicting; extra photographs do not vote away a contradiction. A clear unknown model code also prevents confirmation, even beside a known code. The export reports only its unresolved count and never transmits that arbitrary label. Corrections append history containing previous review, quantity, ownership, sharing and photo metadata. Adding a new view clears the previous identity confirmation. It never changes a design, BOM or existing inventory record automatically.

Unknown or blurred markings produce a concrete follow-up: a sharp full module part-number label, the carrier underside part/revision label, or the developer-kit box part-number label. Mask serial numbers. A generic board appearance, heatsink or connector count cannot establish module, RAM or revision.

## Component evidence

The small offline catalog matches complete public codes only. It separates the module, carrier and developer kit. It does not derive a kit identity from a module/carrier combination; it never infers hardware revision.

- [NVIDIA Jetson Linux 35.3.1 Developer Guide](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/index.html), updated May 19, 2023, “Devices Supported by This Document”: full P3767 variants distinguish Orin NX and Orin Nano capacity. A family-only P3767 marking remains unresolved.
- [NVIDIA Orin NX/Nano bring-up guide, version 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html), “Porting the Linux Kernel Device Tree Files”: P3768-0000 identifies the reference carrier context.
- [NVIDIA Jetson Nano Developer Kit User Guide](https://developer.nvidia.com/embedded/dlc/jetson_nano_developer_kit_user_guide), DA_09402_004, January 15, 2020, printed page 1: P3448-0000 module, P3449-0000 carrier and the two full 945-level kit codes are separate identifiers. Kit codes distinguish the documented A02/B01 carrier configuration; the actual photographed hardware revision still requires its own evidence.

Catalog records retain manufacturer, public code, URL, document revision and locator. Exact source-document byte hashes are unavailable and stored as null, so this is reviewed reference metadata rather than an authenticated local manufacturer-document archive. No manufacturer graph, image or document is copied into fixtures. The catalog is not a compatibility or authenticity validator; physical feasibility remains outside its scope.

## Storage, sharing and integrity

Each grouped item owns original local image snapshots by SHA256. The original PNG/JPEG/WebP byte stream is preserved exactly; the importer only checks a container signature, byte size and hash. A corrupt image with a matching signature can be retained as evidence bytes, but there is no claim it was decoded or understood. External source-file replacement cannot alter the saved original. Changing saved bytes or current metadata causes refusal before an inventory projection is returned.

The ledger binds app identity, project ID and absolute store location. Copying or rebinding the store to a different app/project/path is rejected. Project-only scope is the default. The `set_sharing(item_id, scope='equipment', shared_with=[...], reviewer=...)` API records an explicit list of projects allowed to see equipment; readers must also opt in with include_shared=True. There is no automatic global equipment import or remote sharing. Local raw labels and reviewer text remain local. OS-level account access control is outside this ledger.

Current metadata is a hashed, strict UTF-8 JSON snapshot, selected by an atomically replaced head. Prior snapshots and a bounded correction history are retained. Hashes detect accidental changes but are not authenticated signatures; an attacker controlling the entire store/head can forge or roll back metadata. Single-writer locking covers the entire intake, including quota checks, source copying and head publication; an existing lock refuses before any evidence writes. Revision checks reject stale concurrent publication. Equipment IDs hash an unambiguous tuple of app, project, bound store and group ID, so separator ambiguity cannot merge scoped items. The lock is never automatically removed after a crashed process; inspect it and recover deliberately. A crash can leave orphan evidence/snapshot files, which count against limits and are not silently deleted. Intake preflights both stored byte and file-count quotas, the next snapshot name and metadata serialization before source copying; retained orphan files cannot consume a hidden extra slot.

Limits: 16 grouped items, 6 views per item, 1 MiB per image, 32 MiB stored images including orphans, 256 KiB per JSON state, 32 history events per item, 128 revisions. Duplicate image bytes within a group are ignored; the same bytes assigned to a second group are rejected to avoid duplicate inventory. This cannot detect two genuinely different photographs of the same physical object across separate user-created groups; the user must group views correctly. Local symlink/reparse/network paths and hardlinks are refused. Directory scans are bounded and streaming. No hard wall-clock deadline is promised or measured.

The new ledger offers a CLI/API and inventory_items(...) projection. The existing inventory loader accepts an explicit PhotoLedger and project scope for an optional read projection; old no-argument loads are unchanged and no source inventory files are written. equipment_id collisions refuse instead of merging. Existing GUI/default inventory calls do not yet opt in. Automatic approval review initially rejected adapter ownership; root explicitly clarified these two exact additive paths and permitted one same-call retry, which succeeded. A separate new-test staging request was rejected because its content was missing after an interrupted assembly loop; content was corrected and the single parent-permitted same-tool retry succeeded. Both events are retained in the honest receipt.

## Aster metadata result

`PhotoLedger.result(item_id)` returns a bounded app-owned JSON metadata object. Its typed wrapper is ideaforge.reviewed-photo-inventory.v1. Result keys are project_id, revision, item_id, status, quantity, ownership, scope, shared_with, photos, identities, confidence, unresolved_model_code_count, follow_up, recognition, original_image_bytes_in_bundle, image_verification, local_image_verification and limits. App revision is the ledger's decimal integer revision string.

The shared app exporter supplies the closed aster.research-bundle.v1 envelope and receipts. Binary photo bytes are excluded. `original_image_bytes_in_bundle=false` and `image_verification='unavailable'` explicitly describe Aster's inability to verify original images. The producer separately reports `local_image_verification='sha256-and-byte-count-checked'`. Aster verifies included JSON/text metadata bytes only; declared photo hashes remain unverified there. Result export contains normalized public catalog codes, image hashes/counts and conservative status, but omits arbitrary raw labels, reviewer text, image paths and raw images. Export is local output, not provider transmission or automatic inventory adoption.

## Verification status and licensing

45 unittest methods are authored with self-authored PNG label drawings and manually supplied synthetic observations. Cases include grouped views, conflicts, missing/blurred labels, component-kind mismatch, duplicate avoidance, source replacement, restart, correction history, quantity/ownership/sharing, project isolation, tamper refusal, file limits and provider isolation. Two filesystem-specific tests may skip when symlink/hardlink creation is unsupported. All project tests, compilation, CLI execution and integrations are UNRUN unless a later receipt explicitly records observed execution.

Only Python standard-library modules are added. No OCR or local perception package was selected or installed. No third-party fixture images, private serials or user photographs are published. The manufacturer catalog contains original paraphrased identifier facts and source links, not copied documentation or branding artwork. Existing project licensing is unchanged.
