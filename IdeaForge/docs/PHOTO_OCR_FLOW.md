# Local OCR-to-inventory review

This increment connects the optional local OCR adapter to the existing grouped
photo ledger. It does not add a visual reasoning fallback, train a model, upload
images, search serials, change model selections or validate hardware/CAD/BOM.

Source-only status: all 49 flow regression methods are UNRUN. Native calls are
mocked and every positive receipt is explicitly test_only=true. Their
PNG-signature payloads are deliberately non-decodable self-authored ledger
fixtures. These methods exercise transaction and schema decisions, not pixel
recognition, engine accuracy, native containment, duration or memory usage.
No local command, decoder, OCR process, package install or test was executed.

## Callable path after qualification

Existing manual photo intake copies original bytes into one app/project/root-
bound group and preserves human observations. OCR is a separate explicit path:

1. recognize(ledger, item_id) reads actual fixed selection files and captures all
   current original hashes, ledger revision/hash and current human/OCR review
   state under the existing writer lock. It checks capacity for a full private receipt
   before native admission; this is not a durable slot reservation.
2. The optional adapter performs bounded local OCR outside that ledger lock,
   with its own native-operation serialization and containment guards.
3. Completion reacquires the ledger lock and rechecks the complete capture plus
   exact raw bytes of all three selection files. Stale completion writes no
   receipt and never changes inventory.
4. A fresh immutable private receipt records original/derived hashes, words,
   unrotated boxes, engine/model/code and catalog binding, diagnostic confidence
   and owned-job metrics.
5. preview(ledger, receipt_sha256) returns only recognized public code quotes,
   boxes, source locators and hashes. Unknown words, serial-bearing text,
   engine paths and private reviewer notes stay in the private receipt.
6. approve requires explicit checked-box review of every candidate, expected
   current revision, quantity, ownership and project/sharing scope. One writer
   lock covers receipt/config/photo rechecks, strict preflight, final selection
   recheck and publication. Human observations are not rewritten as OCR output.

There is no OCR GUI added. The actual source path is API/CLI plus the existing
opt-in photo inventory projection. No-argument inventory loaders retain their
existing behavior. These future qualified commands were NOT run:

~~~powershell
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT intake BOARD front.png back.png --reviewer OWNER --same-item-confirmed
python -m core.photo_ocr_flow --store projects/PROJECT/photo_inventory --project PROJECT recognize BOARD
python -m core.photo_ocr_flow --store projects/PROJECT/photo_inventory --project PROJECT preview RECEIPT_SHA256
python -m core.photo_ocr_flow --store projects/PROJECT/photo_inventory --project PROJECT approve RECEIPT_SHA256 reviewed-request.json
python -m core.photo_inventory --store projects/PROJECT/photo_inventory --project PROJECT list
~~~

The review request has exactly expected_revision, reviewer, expected_subject,
confirm_identity, observed_words_confirmed, candidate_ids, quantity, ownership,
scope and shared_with. Copy the exact revision and ALL candidate IDs from the
preview; selecting a preferred view cannot discard other evidence. The checked-
words flag must be boolean true after checking every public quote against its
image box. Quantity is an explicit positive integer, never image count.
Subjects are module, carrier, developer_kit, assembly or unknown.

Boxes use UNROTATED decoded pixel coordinates. The worker does not apply EXIF
orientation; it creates fresh RGB pixels with identity-no-exif transformation.
An EXIF-rotating viewer can show different coordinates. Receipts preserve
original/derived hashes, without promising third-party rendering alignment.
A working demo must show the matching unrotated view. This source-only CLI
has not established visual alignment or recognized any real board image.

## Explicit policy and unavailable state

Production paths are fixed to the app source root:
- ai_provider.json must be the actual exact protocol/provider/app/revision
  object: protocol aster.provider.selection.v1 and provider standalone.
- ai/config.json must be strict finite JSON with explicit nonempty language-
  model provider/model. Other finite settings are retained and hashed.
- photo_ocr_config.json is the explicit optional adapter selection; its exact
  raw byte hash is retained, including formatting differences.

No passed OCR configuration or qualification is shipped. The optional OCR file
is ignored by Git. Missing, disabled, unqualified, malformed or Aster selections
remain unavailable. Missing provider selection never defaults to standalone.
No text/vision provider is invoked; existing Aster vision refusal remains.

IdeaForge uses canonical photo app ID ideaforge and provider ID ideaforge.
HumanoidResearcher keeps legacy provider ID humanoid-researcher distinct from
canonical photo app ID humanoidresearcher. No identity alias is merged.

A test-only policy-root override is absent from the production CLI. The source-
test API requires an explicit flag plus a disabled configuration with no
qualification BEFORE runner admission. The real adapter consequently refuses
before native import/scan/decode/launch. Mocked positive receipts stay test_only.
An injected qualified/enabled selection cannot dispatch the real runner.

The adapter separately checks exact runtime/model/Pillow/code closure, engine,
catalog and actual bounded qualification records. File presence is not
qualification. Engine receipt digests must match the selected configuration.
Local reviewed qualification records are declarations, not authenticated proof
that a test ran. Restart reading validates bytes without requiring an installed
engine; current inventory/result reads recheck actual fixed policy/config.

## Conservative identity

Only complete public codes from the reviewed manufacturer catalog match.
OCR does not repair O/0, join characters, infer a full SKU from a family code,
infer RAM from appearance or guess a manufacturing revision.

A complete module SKU can supply catalog memory only where the official source
binds it. Carrier codes identify carriers, not modules. A module/carrier pair
does not establish a developer kit; that requires its own kit code.
Manufacturing revision remains unknown. Kit marketing names containing A02/B01
do not become an assertion about a module/carrier manufacturing revision.

All captured views remain in the decision. Partial/code-like unknown words,
low diagnostic confidence or same-role conflicts make the receipt unresolved/
conflicting. These groups cannot enter OCR inventory approval, including
provisional approval. They remain private candidates needing readable close-
ups. A complete candidate cannot confirm a wrong requested component kind or
override contradictory earlier human observations.

The confidence threshold is a conservative admission setting, not a measured
probability of identity. Accuracy on actual labels is untested.

The catalog uses reviewed paraphrases and source locators from official
[NVIDIA supported devices](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/index.html),
[NVIDIA carrier bring-up](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)
and [NVIDIA Nano guide](https://developer.nvidia.com/embedded/dlc/jetson_nano_developer_kit_user_guide).
No manufacturer images/graphs/document reproduction or user's images are
published by this increment.

## Storage, correction and isolation

Private canonical receipts are immutable ocr_receipts/SHA256.json files inside
the existing private ledger: 64 KiB/file, 32 files, 2 MiB total INCLUDING
interrupted orphans. Admission checks capacity for a full receipt; completion rechecks quota.
Concurrent callers do not acquire a durable quota reservation; completion can
refuse if another caller consumes that capacity.
Exclusive creation, single-link/type checks, safe paths and exact readback
prevent ordinary overwrite. Invalid or interrupted prior files need explicit
local recovery and are retained. The existing 256 KiB snapshot/32-history/
128-revision limits remain; no silent truncation is introduced.

An optional compact ocr_review stores selected IDs, evidence hashes, safe
public identity summary and the explicitly attributed human checked-box review.
Historical OCR pointers and quantity-reviewer attribution remain separate from
manual observations. Legacy v1 snapshots lacking new optional fields remain
readable by this implementation.

Reading stored evidence recomputes receipt/summary, binds app/project/root/
original photos and verifies the captured immutable ledger snapshot and its
human/review-state hash. Hashes establish byte integrity, not authenticated
origin or independently observed native execution.

Changed/missing/Aster/disabled/unqualified selection makes current inventory/
result provisional with unknown confidence despite historical confirmation.
Synthetic receipt fixtures are always provisional and explicitly labeled in
inventory notes and result. Preview exposes a stale-policy flag while allowing
historical public boxes to be reviewed locally.

Result adds only bounded ocr_provenance: receipt/catalog/engine hashes,
test_only, local-byte-integrity-only verification, and declared-unverified or
synthetic-unqualified qualification. Raw words, unknown codes, private paths,
reviewers, capture/root bindings and engine/model locations are excluded.
Original image verification in Aster remains unavailable, original binary
images remain excluded, and inventory verified stays false.

New views and manual corrections clear active OCR selection while preserving
history. Quantity/sharing corrections invalidate its identity confirmation.
Clear/undo require expected revision and one writer transaction:

~~~powershell
python -m core.photo_ocr_flow --store projects/PROJECT/photo_inventory --project PROJECT clear BOARD --expected-revision REVISION --reviewer OWNER
python -m core.photo_ocr_flow --store projects/PROJECT/photo_inventory --project PROJECT undo BOARD --expected-revision REVISION --reviewer OWNER
~~~

Clear removes active OCR choice, preserving human review, quantity and sharing.
Undo also restores pre-approval quantity/reviewer, ownership and sharing ONLY
when no later item edit exists. Neither silently reactivates earlier OCR
confirmation. History retains that evidence for fresh current capture/review.

Receipt copied into another app/project/store cannot be approved. Equipment
sharing still needs explicit scope, recipient list and opt-in projection.
Use the ignored projects/PROJECT/photo_inventory path shown above; arbitrary
custom store names are not automatically covered by ignore rules.
No private input images, OCR, serials or runtime identity data were exported.

## Remaining real-demo qualification

The flow itself uses Python standard library and adds no pip dependency.
The optional Tesseract 5.5.3/Pillow adapter's pinned dependency/license/native
qualification requirements are documented in [LOCAL_PHOTO_OCR.md](LOCAL_PHOTO_OCR.md).
That document records Tesseract/English model Apache-2.0, Leptonica BSD-2-Clause
and Pillow MIT-CMU; the actual installed wheel/codec/DLL closure remains unqualified. No dependency was
installed or downloaded by this flow work.

A working photo-to-inventory demo still needs a recovered supported runner,
explicit coordinator resource clearance, complete verified local runtime/model/
code/dependency closure, actual containment/timeout/overflow and pixel-positive/
negative/ambiguous/conflict/isolation records, and local readable board photos.
It must show actual quotes/boxes against an unrotated image, correct conservative
identity, explicit quantity/provenance, restart and project isolation.
Mocked flow tests establish none of those native/pixel/duration/memory results.

The sole earlier authorized desktop probe failed before process/session
creation with helper_unknown_error: setup refresh had errors. No retry/bypass
was attempted. All runtime/recognition/build/install/decode tests remain
HOLD/UNRUN pending explicit clearance. No VM or recovered runner is claimed.
