# Optional browser integration: fixture stage

This is a separate, opt-in deterministic adapter, not an enabled NewBrain tool,
Internet browser, signed-in profile integration, or live account assistant.
`python -m aster.browser_integration status` reports its actual scope without
starting a browser. Core Aster still requires no third-party Python packages.

## What this stage does

- Opens a **fresh temporary, sandboxed, headless Chromium context** through the
  optional official Playwright package. It never attaches an existing browser,
  debug port, extension, login session, saved profile, or credentials.
- Reads bundled fixture text, links, and explicitly allowlisted ordinary fields.
  Every page result is marked **untrusted data, never authorization**.
- Navigates between bundled pages, fills a non-sensitive demo field, and clicks
  allowlisted links or a single ordinary fixture form's submit button.
- Previews each fill/click with its exact target, value, effect, destination, and
  applicable fixture terms/charges. A human must confirm the exact one-use token
  interactively; there is no CLI `--approve` bypass for mutations.
- Shows fixture login/signup forms for inspection. Secret/payment/identity and
  file-upload fields are redacted and return a handoff-required status **without
  reading or entering their values**. Login, signup submission, OAuth, persistent
  access, and live account creation remain unavailable. The human handoff is an
  honest stop status, not an implemented connection to a real account website.

## Exact fixture origin and network boundary

The sole approved fixture origin is `http://127.0.0.1:49151`. This address is a
**synthetic label**, intercepted before network access and fulfilled from the
bundled `aster/browser_fixture.py` bytes. The adapter starts no HTTP server and
never contacts a service that happens to be listening on that port. Other local
hosts, ports, files, URLs, and services are not allowed.

The browser context is offline, JavaScript is disabled, service workers are
blocked, and a restrictive CSP disables scripts, frames, resources, and network
connections. A context-wide route handler **never continues any request**. It
fulfills only one exact, previously admitted GET main-frame navigation at a time;
all other requests, redirects, subresources, frames, POST requests, and origins
are aborted. WebSockets are closed before connecting. Downloads are rejected,
popups are closed, and upload APIs are not exposed. There is no arbitrary URL,
selector, JavaScript/eval, shell, file, browser-channel, or executable-path API in
the CLI. The Chromium sandbox is explicitly enabled; launch failure never causes
an unsandboxed fallback.

These are application safeguards for this narrow deterministic fixture stage,
not an OS network sandbox or a security boundary against malicious Python code,
a browser vulnerability, or an attacker with the same OS account. Playwright
runs its own fixed automation protocol internally; no page-provided script or
owner-supplied JavaScript is executed. The adapter does not claim that arbitrary
websites can safely be enabled by adding a hostname.

## Explicit installation and use

Optional installation is an owner/developer action, never automatic:

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python -m aster.browser_integration status
python -m aster.browser_integration read --approve-fixture-origin http://127.0.0.1:49151 --path /form
python -m aster.browser_integration session --approve-fixture-origin http://127.0.0.1:49151
```

In the interactive session, use `navigate /form`, `read`, `fill project-name`,
`click form-submit`, and `quit`. Enter only a non-sensitive demo label. The adapter
cannot determine whether someone types a secret into an ordinary text field; do
not provide real passwords, payment details, personal identifiers, or private
information anywhere in this fixture demonstration. Ordinary demo values appear
in the explicit review and in-memory snapshot, but no session data is saved.

The confirmation token binds one session, URL, revision, page snapshot, action,
exact target, value, and destination. It expires after 60 seconds. A newer preview,
navigation, changed page, cancellation, bad confirmation, attempted execution,
timeout, or session closure consumes/revokes it. No failed action is automatically
retried. The session expires after 15 minutes or 100 operations. Each browser
operation has a 3-second timeout, launch has a 10-second timeout, snapshots are
bounded to 12,000 text characters/32 links, and ordinary values to 200 characters.
The limits are application budgets, not hard CPU/process isolation.

## Evidence and qualification

Dependency-free contract tests are part of standard foundation discovery:

```sh
python scripts/record_browser_checks.py --output test-results/browser-integration/new-unit-run
```

Real browser qualification is explicit and **must fail, not skip**, when the
runtime, browser binary, sandbox, guards, or fixture behavior is unavailable:

```sh
python scripts/record_browser_checks.py --live --output test-results/browser-integration/new-live-run
```

Use a fresh evidence path for every run. The recorder retains source hashes,
complete test logs, outcomes, skips, and environment details for this Aster-owned
feature. It does not copy unrelated upstream private provenance or reports.
`.github/workflows/browser-fixture.yml` installs the official optional dependency
only in separate Ubuntu/Windows fixture jobs when browser files change (or by
manual dispatch), runs required real-engine tests with the sandbox enabled, and
retains results as repository Actions artifacts. Foundation jobs remain free of
this optional installation. An Actions artifact is test evidence; it does not
by itself commit evidence files to the main branch.

Initial cloud qualification found Playwright 1.62.0 present but its default
Chromium binary absent. A separate probe of the preinstalled system Chromium
failed on the cloud executor's denied socket syscall with the sandbox enabled.
No sandbox bypass or browser installation was attempted. Local unit passes are
not live-engine qualification, and pending CI is not a pass. See retained
`test-results/browser-integration/` outcomes for exact run results.

## Deferred real-site work

Real research pages, authentication, signup, form submission, files, persistent
access, payment and sensitive-data handoffs require a separately reviewed adapter,
site-specific scope, user approvals, credential handoff, source provenance and
additional acceptance tests. This fixture stage grants none of those abilities.

Implementation references: [Playwright browser contexts](https://playwright.dev/python/docs/api/class-browsercontext),
[network interception](https://playwright.dev/python/docs/network),
[service-worker restrictions](https://playwright.dev/python/docs/service-workers),
and [browser launch options](https://playwright.dev/python/docs/api/class-browsertype).

## CI runtime compatibility (2026-10-06)

Initial CI for PR #8 installed official Playwright 1.63.0 and Chromium on both
platforms. Ubuntu24 (the current `ubuntu-latest`) then refused all five live
setups with **No usable sandbox** under its existing AppArmor/user-namespace
policy. This configuration remains **unqualified**; no sandbox switch, sysctl,
AppArmor policy, privileges, or live assertions were weakened. Windows installation
succeeded but CP1252 console output could not print the installer's Unicode
progress bar, so no Windows tests ran in that attempt. Raw failure logs are
retained. The recorder now uses UTF-8 console output while preserving original
log bytes, with a dependency-free CP1252 regression test.

Only the separate fixture job now targets `ubuntu-22.04`; foundation CI stays on
`ubuntu-latest`. [Playwright lists Ubuntu22.04 as supported](https://playwright.dev/python/docs/intro)
and [GitHub still provides that image](https://github.com/actions/runner-images).
This is a bounded compatibility target: GitHub began deprecation on September 17,
2026 and [retires it on April 17, 2027](https://github.com/actions/runner-images/issues/14254).
A supported successor must be qualified before retirement. Any successful Linux
live result applies to the exact tested Ubuntu22.04 runner/runtime only, not
Ubuntu24, `ubuntu-latest`, another OS, or the user's computer. The pinned runner's
real sandbox and all unchanged fixture assertions still have to pass fresh CI;
runner selection alone is not proof of runtime compatibility.

The evidence recorder writes the expected stage list before starting and marks
`completed`/`success` only when every scheduled stage has finished and passed as
applicable. A stopped, interrupted, or partially written run is not completed
qualification. `live_browser_qualified` additionally requires a passing live
stage and successful completion of the full scheduled run. Earlier CI receipts predating
these fields must be read alongside their workflow conclusion and full logs.
