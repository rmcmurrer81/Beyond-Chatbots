# IdeaForge Troubleshooting

Report a problem in ordinary language, such as "the motor jitters", "the bracket
binds", or "the display reports error E07". An explicitly attached image remains
an explicit vision input; no project image, PDF or OCR store is discovered.

## Provider context policy

Troubleshooting now reads exactly two project metadata paths:

- `project.json`: bounded identity, title, plan summary, capabilities, subsystems
  and unknowns. Arbitrary extra fields and nested objects are omitted.
- `project_memory.json`: bounded current keyed facts explicitly marked
  `source=user_statement`. Superseded facts, imported/unknown sources,
  `source_text`, extraction payloads and arbitrary extra fields are omitted.

These selected fields are intentional provider inputs. Saved user facts are
model-extracted statements, not independently verified measurements. Users
should supply relevant additional measurements in the current problem report.

There is no recursive collection. README files, free-form research summaries,
fabrication/simulation plans, conversation logs, old incident reports, PDF
versions and passages, photos, OCR, private staging and incidental filenames
remain outside the default troubleshooting context. Excluded content is not
loaded through the raw PROJECT block either.

All selected source and incident paths stay under the canonical project root.
Linked components, symlinks, junction aliases and hardlinked metadata sources
are refused, including links into excluded stores inside the same project.
Source JSON reads are limited to 65,536 bytes. Project projection is limited to
3,500 UTF-8 bytes; individual fields and list counts are bounded. Local context
is limited to 12,000 UTF-8 bytes even if configuration asks for more. Zero or
negative local budgets yield no local block. The independently required
project identity/projection is still included in diagnosis and query creation.

Problem text permits at most 4,000 characters and 8,000 UTF-8 bytes. Explicit
vision analysis is bounded to 6,000 UTF-8 bytes; web context to 8,000 bytes.
Query count, query length, result count and result fields have hard caps.
Provider request byte limits remain enforced by the existing provider boundary.
No concurrent hostile filesystem path-swap guarantee is claimed.

## Incident states and reports

Incident state is `open` or `resolved`. Chat and persistence use the same
deterministic conservative classifier:

- A complete, direct confirmation such as "That fixed it", "It works now",
  "The problem is fixed" or "I solved it" resolves the active incident.
- Current failures, including negative fix reports, broken components and
  crashes, reopen a resolved incident. Failure overrides a positive phrase
  anywhere in a mixed report.
- "Reopen this incident" explicitly reopens it.
- Questions, hypotheses, quoted or historical success, negation and ambiguous
  success do not establish a new resolution. Uncertainty preserves the prior
  state and is retained as a report. More complicated confirmations may need
  a short direct confirmation before they are marked resolved.

Every recorded follow-up retains its text, classification, time and from/to
states. Reopening clears the current `user_outcome` while keeping prior
resolutions in `outcome_history`. Legacy contained absolute ACTIVE pointers
migrate to relative paths with project identity and canonical root binding;
foreign pointers, copied bindings and unsupported states are refused.

A failed follow-up routed through chat continues the same incident and saves
a new report under `REPORT-<unique-id>.md`. The original `REPORT.md`, original
problem and prior outcome history remain available. New unrelated diagnoses
create unique incident directories, preventing same-second filename collisions.

Incident records and histories have a 262,144-byte read/write budget. An
over-budget follow-up is refused before replacing the previous record or report.
Individual JSON replacements are atomic; record/ACTIVE updates are not a
multi-file transaction. An interrupted publication can leave an unreferenced
new report or incident. Existing reports are retained, and recovery is manual.

## Verification status

The synthetic regression source contains 29 test methods, covering intercepted
calls through the actual decorated `diagnose`, private markers and filenames,
budgets, file ordering, old/current PDF versions, Unicode, linked/hardlinked
sources, outcome classification, chat routing, restart, cross-project pointers,
legacy migration, report preservation, collision avoidance and bounded refusal.

Suggested bounded command in a functioning checkout:

    python -m unittest discover -s tests -p "test_troubleshooting.py" -v

All 29 tests, Python compilation and live/provider execution are **UNRUN** for
this change: execution setup failed before any local command. No private
document, live model, firmware or hardware was used. Files were published and
read back through the private GitHub connector. See
`docs/test-receipts/2026-10-10-troubleshooting-isolation.json` for exact commits,
source checks, review findings and the execution error. Source review cannot
establish runtime success. Symlink/hardlink cases can explicitly skip on
filesystems that cannot create those fixture links; any future skips must be
reported separately from passes.
