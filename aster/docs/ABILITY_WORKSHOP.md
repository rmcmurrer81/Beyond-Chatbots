# Ability Workshop: reviewed finite text recipes

## Implemented boundary

The Workshop extends immutable `Abilities` proposals with real bounded recipe tests, receipt-bound owner review, explicit version installation, audited rollback, and a separately requested pure-text invocation. It is deterministic local application code. It does not depend on a qualified NewBrain runtime and does not generate new abilities or imply that NewBrain learned anything.

**Python, shell, downloaded programs, expression evaluation, imports, subprocesses, network requests and arbitrary file operations remain unsupported and inert.** Even an approved `.py` proposal cannot run through the Workshop. Existing `Abilities.select()` and its rollback still only record future selections and cannot activate a recipe.

The interpreter operates on strings in the existing process. “Isolated tests” means fresh in-memory strings per test case, with no recipe access to the filesystem, environment, host objects or network. **This is not an OS/process sandbox, wall-clock timeout, hostile-owner security boundary or proof of arbitrary-program safety.** Every operation and data size has a fixed upper bound. There are no loops, regular expressions, recursion, templates with code access, callbacks or generated instructions in the recipe language.

Transformations return text. They do not create or overwrite workspace output files. A future file-output extension must use a separately reviewed exact destination and the existing scoped `Files` change journal. This version does not grant that extension permission.

## Strict source format

Create the source as an ordinary bounded workspace file and snapshot it with the existing `Abilities.create(name, path, permissions=[], supersedes=...)` API. A new version must explicitly supersede the latest proposal of that name. The Workshop reads the immutable source snapshot rather than whatever later occupies the original path.

```json
{
  "format": "aster.text-recipe.v1",
  "steps": [
    {"op": "strip"},
    {"op": "replace", "old": "draft:", "new": ""},
    {"op": "uppercase"},
    {"op": "prefix", "text": "TITLE: "}
  ]
}
```

Only these exact operation schemas are accepted:

- `{"op":"strip"}`: remove leading and trailing Unicode whitespace.
- `{"op":"uppercase"}`: Python's deterministic Unicode uppercase operation.
- `{"op":"lowercase"}`: Python's deterministic Unicode lowercase operation.
- `{"op":"replace","old":"literal","new":"replacement"}`: replace every non-overlapping literal occurrence. `old` must not be empty. This is not regex substitution.
- `{"op":"prefix","text":"literal"}`: prepend literal text.
- `{"op":"suffix","text":"literal"}`: append literal text.

Unknown or missing fields, duplicate JSON keys, unrecognized formats/operations, invalid UTF-8/surrogates, nonfinite values, incorrect types and oversize values are rejected. Declared external permissions must be empty; permission labels never grant anything.

Limits, in UTF-8 bytes unless stated otherwise:

| Item | Limit |
| --- | ---: |
| Source JSON | 32,768 bytes |
| Recipe steps | 1–16 |
| Input per example or invocation | 16,384 bytes |
| Literal operand | 16,384 bytes |
| Each intermediate and final output | 32,768 bytes |
| Test examples | 1–16 |
| Combined test input + expected text | 262,144 bytes |
| General history/list view | Latest 100 records |

Replacement expansion is checked before allocating its result. Prefix, suffix and Unicode case conversion have bounded one-step allocations, and each intermediate result is checked immediately. An oversized intermediate fails even if a later step would shrink it. The test suite also checks exact limit acceptance and Unicode byte accounting. There is no wall-clock timeout; limits constrain work, not a guaranteed latency on every machine. The existing Store database size limit applies, and exhaustion fails rather than silently pruning history.

## API and explicit workflow

```python
from aster.abilities import Abilities
from aster.ability_workshop import AbilityWorkshop

# store and files are the application's existing Store / Files pair.
abilities = Abilities(store, files)
workshop = AbilityWorkshop(store, files)
proposal = abilities.create('title-cleaner', 'recipes/title.json', [])

receipt = workshop.test(
    proposal['id'], proposal['source_sha256'],
    [{'input': 'draft:hello', 'expected': 'TITLE: HELLO'}],
)

# Inspect the stored snapshot, never a potentially changed workspace source file.
source = workshop.source(proposal['id'])
# The caller shows source['source_text'], its hash and the real receipt for review.
review = workshop.review(
    proposal['id'], 'approved', 'Reviewed these exact source bytes and results.',
    proposal['source_sha256'], receipt['id'],
)

# This records installation only; it does not invoke the recipe.
workshop.install(proposal['id'], proposal['source_sha256'], review['id'])

# Preview computes the pure result and saves the exact input/output plan.
plan = workshop.preview_run('title-cleaner', 'draft:meeting notes')
# Show plan['input_text'], plan['output_text'], source hash and review to owner.
# A separate explicit request invokes this one-time plan.
result = workshop.run(plan['id'], plan['input_sha256'])
assert result['output_text'] == 'TITLE: MEETING NOTES'
```

Methods and returned state:

- `source(proposal_id)` returns the exact immutable source snapshot for review, independent of approval/rejection. It includes `source_sha256`, `source_bytes`, and verbatim `source_text` for valid UTF-8 (up to the existing proposal file limit of 256 KiB). `utf8_valid=false`, `source_text=null`, `recipe=null`, and `unsupported_reason=invalid_utf8` explicitly describe undecodable bytes. Strictly valid, permission-free recipes also include parsed `recipe`, `recipe_supported=true`, and `status=supported_recipe`. Other source remains inert and inspectable with `recipe_supported=false`, `status=unsupported_source`, and an explicit reason. Source integrity is checked; no source or recipe is executed. Consumers must display source text literally rather than evaluate it or render it as HTML.

- `test(proposal_id, source_sha256, cases)` accepts a JSON-compatible list of exact `{"input": str, "expected": str}` objects, convenient for a CLI `cases_json` field. It executes every valid bounded example and records actual/expected/input hashes, per-case pass/fail/error, the full cases hash, exact proposal/source hash and interpreter implementation/Python/Unicode runtime fingerprint. A fixture mismatch or output limit produces a failed actual receipt. Invalid source or invalid cases do not produce a test receipt.
- `review(proposal_id, verdict, note, source_sha256, test_receipt_id=None)` supports `approved` and `rejected`. Approval requires the newest actual passing receipt for this exact proposal/source/interpreter. Rejection can omit the receipt or cite its latest receipt, including a failed one. The owner note remains a declaration. It cannot turn a failed test into a pass.
- `install(proposal_id, source_sha256, review_id)` requires the latest source-bound owner approval and its still-current passing receipt. It returns proposal capability state. It grants no external permissions and never invokes the recipe.
- `preview_run(name, input_text)` requires a current eligible installation and returns a single-use plan with `id`, input/output text and SHA-256 digests, source/interpreter hashes, installation sequence, review ID and test receipt ID. Preview itself computes the pure transform; it is not a subprocess dry run. Its `status` is `awaiting_explicit_run` and `output_is_preview` is true.
- `run(plan_id, input_sha256)` requires an explicit invocation of that exact saved input. It rechecks the current installation/review/receipt, recomputes output, validates both input and output, and atomically records one completed run. Reusing a successful plan is rejected. It returns `status=completed`, exact output, hashes, `recipe_interpreted=true`, `code_executed=false` (no source program execution), and no external effects or permissions.
- `rollback(name)` appends a restoration of the preceding installation, only if the target version is still approved with a current passing receipt. It never executes a recipe and never rewrites history. Repeated rollback walks toward the beginning rather than toggling indefinitely. Rollback does not grant approval to a revoked prior version.
- `get(proposal_id)` returns `blocked`, `ready_to_install`, `installed` or `installed_blocked`, plus `blocked_reason`, historical test presence/latest pass result, review/receipt IDs, current installation sequence and live `can_run`.
- `installed(name)` returns the same live state for the current pointer, or `not_installed`.
- `status()` reports capability availability, limits, interpreter hash, and current installed names/states; list truncation is explicit.
- `receipt(receipt_id)` reads a saved actual-test receipt without raw example input or expected text.
- `list()` shows the latest 100 proposals; known earlier IDs remain readable with `get`.
- `history(name)` returns the latest 100 installation/rollback records with total count and a truncation flag.

UI/CLI consumers should inspect `WorkshopBlocked.reason` and live `can_run`; they must not infer authority from an installation pointer, a prior “approved” label, a passed fixture, or a future-selection record. The API enforces state binding; the embedding UI is responsible for soliciting the owner's explicit review, install and run commands. It does not cryptographically authenticate a human reviewer.

## Revocation and failure behavior

- An approval made solely through the older `Abilities.review()` cannot substitute for a Workshop receipt-bound review.
- A later rejection through either review API immediately blocks the current installation and all pending plans.
- A later legacy approval leaves a Workshop review stale. It does not revive the old pointer.
- Any new test receipt invalidates the older review, even if both receipts passed. Approve the new receipt and explicitly reinstall before using it.
- Any newer Workshop review requires reinstalling that exact approval. A revoked version cannot be run by retaining its old pointer.
- Changing interpreter implementation bytes, Python implementation/version, or Unicode runtime version invalidates previous receipts. Retest, review and install against the new interpreter.
- A new installation or rollback invalidates earlier pending run plans, including when the same proposal is restored.
- Explicit rollback from a rejected current version to a still-approved earlier version is allowed. The target version's own latest review remains mandatory.
- Failed audit writes roll back test, review, install and run database changes. A run whose transaction failed can be explicitly retried with the same unconsumed plan. No transformation output file has been written to recover.

Histories are append-only with SQLite update/delete guards. This protects against accidental API/SQL rewriting, not an owner who can replace the database, remove triggers or modify program code. SHA-256 bindings detect accidental mismatch; they are not authenticated external attestations.

## Privacy and verification

Test receipts and generic audit events contain hashes, bounded status and record identifiers, not raw test text, source bytes or review notes. Raw source snapshots and owner review notes already live in the existing owner-local database. Prepared run plans intentionally store the exact input and output there so a later explicit invocation can be bound and resumed across restarts. These plans are private local state, not encrypted against their owner or a compromised owner account. Do not put credentials into recipes or run inputs.

Focused automated tests use real SQLite state and the real finite interpreter. Coverage includes all six operations, immutable snapshot inspection after workspace edits/rejection, explicit invalid-UTF-8 inspection, unsupported programs and permissions, exact field/Unicode/byte limits, multiplicative and intermediate expansion, source/receipt integrity, stale tests/reviews/interpreter/installations/plans, rejection through both APIs, auditable multi-version rollback, no network/subprocess/Files calls during transforms, append-only history, crash/reopen persistence, single-use runs, and transactional failure rollback.

Run the affected regression suites:

```sh
python -m unittest discover -s tests -p 'test_abilit*.py' -v
python -m compileall -q aster/ability_workshop.py tests/test_ability_workshop.py
```

Dated results, every failed/passing run, commands, environment details, source hashes and fixes are retained under `test-results/2026-10-05-support-modules/ability-*`. These tests qualify this deterministic recipe slice on the recorded environment. They do not qualify an OS sandbox, arbitrary program execution, NewBrain code generation, production security against a hostile owner, or unrun native desktop/Windows/macOS behavior.
