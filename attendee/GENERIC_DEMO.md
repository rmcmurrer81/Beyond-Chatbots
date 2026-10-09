# Generic demo — awaiting executable release

**Status: pending. No attendee command sequence has been validated, and no new demo was run to prepare this page.**  
Prepared October 8, 2026, against the public version 12 presentation. Rechecked October 9 against version 13; the historical demo results and pending executable/capture status are unchanged.

The intended five-minute demo is a **generic fitted-cell GLIF simulation with synthetic input**, if that exact package is approved for release. GLIF means generalized leaky integrate-and-fire: a bounded model of an individual cell's electrical response. It is not a complete NewBrain, an identity, a conversation system or a whole brain.

## Evidence already available

The [reviewed-results summary](../presentation/Reviewed-Results.txt) reports a clean nine-record starter that passed 30 tests. Its deterministic simulation produced 10,000 samples and 22 spikes under the selected pulse, zero spikes under zero/negative controls, and an identical repeat. These are historical reviewed results. Source, reference parameters and the exact pulse settings are **not included** in the current public package.

A script may describe a starter as public in intent. Current executable availability must be established by actual released files, a source/version manifest and a run receipt. The [repository overview](../README.md) identifies implementation packages as still being prepared.

## What must be supplied before this becomes runnable

| Required item | Current status |
| --- | --- |
| Approved public source path, commit and exact file manifest | Pending |
| License/rights notices covering the actual code and reference inputs | Pending |
| Supported platform, interpreter, dependency versions and measured resource needs | Pending |
| Installation and five-minute invocation commands tested against that exact release | Pending |
| Synthetic input files and their exact parameters | Pending |
| Expected output files, tolerances and a baseline run receipt | Pending |
| Repeat/control commands and a safe reset procedure | Pending |
| Actual same-demo capture and captions | [Pending](DEMO_RECORDING.md) |

No install, simulation or reset command is supplied here because the public release does not yet establish one. Do not guess parameters from the reported spike count, run private packages or substitute unrelated code and call it this demo.

## Planned five-minute sequence

This is a run plan, not an executed walkthrough:

1. **Minute 0–1:** identify the released commit, input fixture, platform and notices.
2. **Minute 1–2:** run the qualified synthetic pulse and show the actual saved output.
3. **Minute 2–3:** run the documented zero/negative controls and inspect their output.
4. **Minute 3–4:** repeat the same run and compare the released criterion for determinism.
5. **Minute 4–5:** explain the narrow result, show the recorded resource measurement and use the qualified reset procedure.

The historical 22-spike result is not a guaranteed output for a changed release. The released demo must define its own verified baseline. If the approved package differs from the starter described above, this page must be revised before it is advertised as runnable.

[Start here](START_HERE.md) · [Help test](HELP_TEST.md) · [Reuse policy](REUSE_POLICY.md)
