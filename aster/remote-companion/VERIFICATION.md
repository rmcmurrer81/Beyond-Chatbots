# Verification: 2026-10-04

Environment: cloud Linux; Python 3.12.14, OpenSSL 3.5.8, SQLite 3.53.1,
Node.js 24.19.0. No third-party packages installed.

- Ten Python tests pass using real client/server HTTP requests over loopback,
  temporary databases and fixture-only credentials. Both relay transport and
  Aster pending-prompt persistence/receipt delivery are exercised. Saturated
  prompt capacity reserves receipt slots; batches of 50 full-size Unicode and
  control-character-heavy messages remain within bounded transport limits.
- Five Node built-in test-runner tests pass using a deterministic DOM harness:
  durable local queue/reload/expiry/cap, HTML-as-text receipts, clear during in-flight send, repeat inbox
  deduplication, stop during in-flight response, grant expiry and safe retry.
- Python compileall and JavaScript syntax checks pass.
- Cloud browser navigation to the temporary loopback preview was blocked with
  `net::ERR_BLOCKED_BY_CLIENT`. No alternate route was used to bypass it; the
  temporary preview listener was stopped. **No screenshot or visual browser
  verification is claimed.** The DOM harness is not a browser or device test.

Not run: public HTTPS deployment, TLS certificate issuance, Cloudflare port,
real user credentials, workstation installation, Android/iPhone browser testing,
PWA installation, public network disconnect/reconnect, background execution,
push notifications, voice/WebRTC/calling or actual NewBrain responses.

Manual acceptance before an eventual deployment: verify a trusted HTTPS origin,
owner-only enrollment and revocation, phone and laptop layout/keyboard behavior,
real browser reload/back/forward/disconnect flows, service worker update/offline
behavior, installation support and network transitions. Secure deployment needs
its own review; this reference server is not production Internet hosting.

## Desktop coexistence extension: 2026-10-05

The new explicit `--desktop` route passed the 29-test remote suite on cloud Linux
(28 passed and one native-display skip in the shell). Running on the actual cloud
Linux desktop then passed all 37 dashboard tests and the new native 50-message
coexistence test, with no skips. The separate native visual fixture showed 50
saved pending requests, zero jobs and remote polling enabled. Existing five Node
DOM-harness tests and syntax/compile checks also passed.

The scoped [test record](../test-results/2026-10-05-desktop-remote/README.md) retains
commands, UTC timestamps, logs, screenshot, crash/retry/queue/shutdown evidence,
tooling limitations and untested stages. No public deployment, user workstation,
physical phone, live pairing, microphone or actual NewBrain inference was used.
