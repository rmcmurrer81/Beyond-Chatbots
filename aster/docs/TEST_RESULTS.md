# Aster test-results index

Recorded 2026-10-04. Machine-readable entrypoint: [test-results/index.json](../test-results/index.json).

This is a curated record of known milestone results, including failures. It is not an exhaustive archive of transient development runs whose evidence was not retained. No application tests were rerun merely to assemble this history.

## Verified GitHub CI history

Counts below are core-suite test cases. Skips are not passes. Every per-run receipt contains the source head SHA and Git tree, the actual Actions checkout SHA and tree, exact recorded commands, runner environment, timestamps, job/step conclusions, failure/skip details and evidence links.

| Run | Milestone | Windows | Ubuntu | Detail |
| --- | --- | --- | --- | --- |
| [37222100109](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37222100109) | Windows candidate: retained failure | 36 passed, 3 failures, 11 errors, 2 skipped | 33 passed, 19 skipped | [receipt](../test-results/ci/37222100109.json) |
| [37222565780](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37222565780) | Windows correction | 51 passed, 2 skipped | 33 passed, 20 skipped | [receipt](../test-results/ci/37222565780.json) |
| [37223693621](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37223693621) | Voice and inert ability proposals | 84 passed, 4 skipped | 68 passed, 20 skipped | [receipt](../test-results/ci/37223693621.json) |
| [37224063935](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37224063935) | Voice/proposals evidence checkpoint | 84 passed, 4 skipped | 68 passed, 20 skipped | [receipt](../test-results/ci/37224063935.json) |
| [37229004947](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37229004947) | Desktop and local research export | 152 passed, 5 skipped | 136 passed, 21 skipped | [receipt](../test-results/ci/37229004947.json) |
| [37229264003](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37229264003) | Desktop evidence checkpoint | 152 passed, 5 skipped | 136 passed, 21 skipped | [receipt](../test-results/ci/37229264003.json) |
| [37230656897](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37230656897) | Desktop merged main | 152 passed, 5 skipped | 136 passed, 21 skipped | [receipt](../test-results/ci/37230656897.json) |
| [37231056434](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37231056434) | Startup/recovery/RAM candidate: retained failure | 214 passed, 0 failures, 14 errors, 8 skipped | 213 passed, 23 skipped | [receipt](../test-results/ci/37231056434.json) |
| [37231361624](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37231361624) | Startup owned-path fixture correction | 229 passed, 8 skipped | 213 passed, 24 skipped | [receipt](../test-results/ci/37231361624.json) |

Every successful platform job above additionally passed 10 relay/bridge Python tests, 5 Node checks and 1,055 Java offline protocol assertions; those counts were verified in each job's logs. Windows companion and compile stages were skipped after each of the two failed Windows core runs. They are not credited with companion passes.

For pull-request runs, Actions tested a synthetic merge commit, not literally the candidate head commit. Git-tree equality was verified for all listed runs except the first failure, 37222100109. That merge added the five original supplied voice assets from main; its receipt lists the difference. The corrected startup run 37231361624 tested checkout `9e781f01cd5037ee815cd01838b7e702afd47c52`; both that checkout and head `ea2f0168bd6b88de38f4cecf7210877478a81869` have tree `5f0b127bcf4d98461a029f7a1143cac602293177`.

### Retained failures

- First Windows adapter candidate: 3 failures and 11 errors. Native rename returned WinError 87; a POSIX-only registration fixture was also invalid on Windows. The corrected run is recorded separately.
- First startup candidate: 14 fixture errors because the runner TEMP spelling contained an ambiguous Windows alias. The owned fixture was normalized; production alias rejection remained in place. The corrected run passed 229 executed Windows tests, with eight explicit platform skips.

## Historical local checkpoints

The [local receipts](../test-results/local/checkpoints.json) preserve the evidence and missing-field reasons.

- Initial foundation: 30 passed; compile passed; retained process-restart/crash checks and narrowly qualified resource observations.
- Windows candidate on Linux: 33 passed, 19 native-Windows skips.
- Voice/inert ability proposals: 68 passed, 20 native-Windows skips; focused voice 17 and registry 15 checks were reported.
- Desktop/export headless: 136 passed, 21 platform/display skips.
- Desktop graphical session: all 37 focused dashboard tests passed in 0.872 seconds. [Retained native test log](../test-results/local/desktop-native-dashboard.log).
- Startup pre-correction: 213 passed, 23 platform/display skips.
- Startup final local correction: 213 passed, 24 skips, 237 collected. The local workspace had no Git metadata; no exact historical source manifest is available, so its commit/tree are null and source equivalence is not asserted.
- Historical desktop manual UI checks, remote companion verification and Android offline protocol checks are separately preserved.
- Fresh manual startup/recovery/RAM visual review: BLOCKED by the tool approval layer. No alternative route or new visual pass is claimed. Automated Windows Tk smoke success is separate evidence.

Local historical timestamps, commands and source identifiers are null where the original evidence does not establish them. The native log is a curated test-only artifact; full CI logs and personal credentials were not copied into this repository.

## Scope and limits

The results qualify deterministic software mechanics. They do not qualify live NewBrain conversation, generated speech, arbitrary ability execution, public remote hosting, physical phones, APK/device behavior or a user's installed workstation. Process-crash fixtures are not physical power-loss tests. Startup registry checks use injected fake backends; actual owner-approved installation remains separate.

Companion sources: [remote verification](../remote-companion/VERIFICATION.md), [Android validation](../android-companion/VALIDATION.md). Milestone narrative: [foundation validation](VALIDATION.md). Separate experimental/vendor component receipts are outside this bounded history.

## Keep future results

For every new Aster test, save a dated receipt under `test-results/` and link it from the machine-readable index. Include source SHA/tree or a local source manifest, environment, exact commands, times, pass/fail/skip counts, meaningful diagnostics, limitations and CI links. Preserve failures and earlier receipts. Use null plus a reason for unknown values; never infer execution from collection or turn skips into passes. Store concise diagnostics without secrets, credentials or wholesale raw service logs.

Index integrity checks are recorded in [index-validation.json](../test-results/index-validation.json).


The [local archive-integrity regression receipt](../test-results/local/archive-integrity-check.json) records the exact command and source-file fingerprint for the checkout hash/count test. CI repeats this check on Windows and Linux.

## Synthetic vision experiment

[Vision receipts and retained failures](../test-results/vision-lab/README.md) separate
mechanical checks, measured synthetic perception, independent review and native CI.
They do not qualify real camera/screen capture, video understanding or production
NewBrain integration.

## Synthetic temporal association (opt-in)

The [temporal lab](TEMPORAL_VISION_EXPERIMENT.md) measures causal engineered
identity tracking independently of unchanged NewBrain color/shape labels.
Development, held-out, independent review and native checks are recorded separately
in [its retained results](../test-results/temporal-vision/README.md). No production
activation, live capture, natural-video or user-PC claim follows from these tests.
