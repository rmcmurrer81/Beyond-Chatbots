# App connection status

IdeaForge and Humanoid Researcher currently provide an opt-in per-user research
catalog in `KiraLabs/research-exchange-v1/catalog.sqlite3`. On Windows the base is
`LOCALAPPDATA`; on POSIX it is `XDG_DATA_HOME` or `~/.local/share`.

Run `python -m aster apps` to discover recent registrations, or supply an explicit
`--catalog /path/to/catalog.sqlite3`. This is bounded, read-only discovery. The
path recorded by an app is untrusted metadata, not an instruction to import,
launch or inspect that installation. A recent registration does not prove a
running app or installed command adapter.

**Current connection capability: discovery only.** The existing catalog's grants
name the two research apps, not Aster. Aster does not query research records,
pretend to be either recipient, widen grants, or import their Python modules.
There is no existing network command server or action executor to call.

A later version needs separately reviewed named app APIs and an explicit Aster
recipient grant before reading project research. Those APIs should accept exact
project IDs and bounded structured inputs; preserve provenance; expose status,
stop/cancel and output receipts; and never let research text become executable
instructions. No shell command, discovered import path, open-ended filesystem
scope or private project access should be inferred from registration.
