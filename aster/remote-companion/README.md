# Aster remote companion: messaging milestone

A small, no-paid-dependency browser companion for a phone or laptop, with a durable relay
and an **outbound-only** workstation bridge. The workstation can remain on home
Wi-Fi: it polls the relay; no port forwarding or inbound workstation port is
needed. This is source code and a tested local prototype, not a deployed service.

## What is real today

- Responsive web app, manifest and offline application shell; add-to-home-screen
  availability depends on the browser. No store download or paid dependency.
- Up to 50 unsent messages saved on the phone/laptop, with 24-hour expiry.
- Single-owner relay with separate companion/workstation credentials, expiring
  grants, bounded SQLite queue, immutable IDs, recipient-only acknowledgement,
  rate limits and owner-bound database.
- Foreground workstation bridge that saves incoming text in Aster's existing
  prompt history and returns an honest delivery receipt. Explicit `--desktop`
  mode keeps the desktop open while its single state-owning worker saves messages.
- No arbitrary command, file write, job execution, research agent or model loader
  is exposed through the remote protocol. Text that resembles a command stays text.

**NewBrain is unavailable.** Saved messages remain `waiting_for_newbrain`. A
receipt means the workstation saved the message, not that an AI understood or
answered it. Voice, calling, push alerts, microphone access, background phone
execution and automatic news updates are not implemented. Closing the browser
stops delivery until it is reopened and paired again. This is not an emergency
notification channel.

## Privacy and pairing

This milestone uses **manual owner provisioning**, not open registration. An owner
must approve and separately provision two independent cryptographically random
bearer tokens of at least 32 characters, and a grant expiry no more than 30 days
away. Never reuse a password or put tokens in URLs, Git, screenshots or chat.
There is deliberately no unauthenticated pairing/invitation API and no automatic
credential generator or account signup. A polished one-use invitation flow is a
future milestone. The app asks for only the companion token; never give it the
workstation token. A matching token authenticates the configured owner and role;
it is not a claim of per-human identity or multi-user isolation.

Tokens are hashed in relay memory with Python's standard SHA-256 and compared
with `hmac.compare_digest`. Browser tokens live only in memory. Relay/bridge
process tokens come from their environment. Revocation means stopping the relay
and restarting with replacement owner-provisioned credentials. Expired grants
fail closed. There is no weak/no-auth mode, fallback credential or checked-in
live secret. Tests use clearly invalid, temporary fixture credentials only.

Transport outside loopback requires verified HTTPS. TLS uses Python's OpenSSL
backed `ssl` module, never custom encryption. This is **not end-to-end encrypted**:
the relay operator can read messages. Device localStorage, relay SQLite and Aster
history contain unencrypted text. Use trusted/private devices and an owner-private
state directory; never place state in a shared folder. Local queue clearing does
not recall messages already sent to the relay or remove workstation history.
Receipt notices in the browser are session-only after acknowledgement.

## Local verification (no setup, accounts or external requests)

Requirements: Python 3.10+ and Node.js 18+ for the optional JavaScript syntax check.
The bridge imports the adjacent Aster foundation. Its bounded NTFS adapter and
these loopback bridge tests passed on the actual Windows Server 2025 CI runner,
as well as Linux. See the root validation record for exact versions and limits.
The web client works independently in modern phone/laptop browsers; no physical
phone or user-workstation installation has been tested.
There are **zero third-party runtime packages** and no package installation step.

From the repository root:

```sh
cd remote-companion
PYTHONPATH=..:. python -m unittest discover -s tests -v
python -m compileall -q aster_remote tests
node --check web/app.js
node --check web/sw.js
node --test tests/test_web.cjs
```

The tests run actual HTTP requests over loopback, with temporary SQLite state.
They test both clients, pending-prompt persistence, receipts, durable reconnect,
lost acknowledgement, duplicate/replayed IDs, wrong credentials/owner, role
separation, expired grants/messages, UTF-8 size limits, HTML text rendering hooks,
security headers and rate limits. These do not prove a real phone or public
network connection. See `VERIFICATION.md` for the exact tested stages.

## Approved owner setup later

Do not run a public deployment just to try this source. Provisioning persistent
credentials, account signup, public hosting and phone installation remain separate
owner-approved setup steps. No service has been selected or configured here.

After that approval and secure provisioning, the relay accepts these environment
variables (values intentionally omitted):

- `ASTER_REMOTE_OWNER`: stable owner label, not supplied by incoming requests
- `ASTER_REMOTE_COMPANION_TOKEN`: companion-only random bearer secret
- `ASTER_REMOTE_WORKSTATION_TOKEN`: distinct workstation-only random bearer secret
- `ASTER_REMOTE_GRANT_EXPIRES`: Unix timestamp, within the next 30 days

Run in an owner-private directory. Keep the database filename there. From this
folder, an explicitly approved local preview would be:

```sh
python -m aster_remote.relay --database /private/owner/path/relay.sqlite
```

The default binds only `127.0.0.1:8765`. Non-loopback binding requires `--cert` and
`--key`; there is no certificate-warning bypass. Python's basic HTTP server is a
reference/testing implementation, not a hardened Internet-facing service (https://docs.python.org/3/library/http.server.html). Public
production deployment needs a reviewed managed server/edge port, abuse defenses,
resource limits, secure secret provisioning and operational monitoring. Do not
expose this reference HTTP server directly to the Internet.

The workstation bridge needs only its scoped token and the approved relay origin:

```sh
PYTHONPATH=..:. python -m aster_remote.workstation \
  --relay https://YOUR-APPROVED-RELAY.example --state /private/owner/path/aster
```

The example hostname is a placeholder, not a service. The bridge polls every ten
seconds; Ctrl-C stops it. `--once` does one pass. `--allow-loopback-test` permits
HTTP only to literal localhost/loopback for testing. Redirects are rejected, TLS
certificates are verified, and no system startup service is installed. Aster's
state lock is acquired per message in standalone mode; a busy workstation leaves
relay messages unacknowledged for later retry. **Do not run standalone mode against
an open desktop.** Use the explicit integrated mode instead:

```sh
PYTHONPATH=..:. python -m aster_remote.workstation --desktop \
  --relay https://YOUR-APPROVED-RELAY.example --state /private/owner/path/aster
```

This reuses the same owner-provisioned workstation token environment variable;
it does not provision credentials, start a relay, open a listener, or install a
service. Ordinary `python -m aster desktop` remains offline. `--desktop` and
`--once` cannot be combined. Run only one workstation bridge/desktop per owner.

### Desktop delivery and shutdown guarantees

An outbound transport thread fetches and validates at most 50 text messages. It
submits immutable, bounded text through a separate queue (maximum 50 items, each
up to 4 KiB) to the desktop's existing SQLite-owning worker. That thread alone
writes state; the lifetime state lock remains intact and rejects other writers.
Network waits never run on the Tk or state-owning thread. Local UI actions take
priority between remote messages, and remote completions do not release the UI's
single-flight guard. Requests refresh with the usual five-second desktop refresh
or the Refresh button; they do not overwrite unsaved editors.

A pending local confirmation pauses remote commits until the owner confirms or
dismisses it. Remote text cannot approve or dismiss a ticket, dispatch a job, load
a model, or execute instructions. Expiry is checked again before saving. Invalid
or expired messages, full queues, failed commits and unavailable state are never
acknowledged as saved. The relay retains unacknowledged messages until expiry.

Each prompt uses `remote-<message ID>`; its prompt and journal event are one
transaction. Only after commit does the transport send the deterministic receipt
and acknowledgement. A lost response or process crash after commit retries the
same ID without adding another prompt or journal event; changed-body ID replays
are rejected. This is exactly-once local persistence for each immutable message
ID, with retryable transport, not a guarantee of delivery after expiry.

Closing rejects new submissions, stops polling, and abandons uncommitted queued
text without acknowledging it. Accepted local actions finish normally. A remote
commit already in progress may finish, and retries remain deduplicated. Close is
nonblocking for Tk; process exit waits for an in-flight network request to return
(the client uses a ten-second socket timeout). No receipt/ack is initiated after
the poller observes stop. Restart with the same state and relay to retry unexpired
messages. The status footer distinguishes polling, retrying and disabled mode;
only error types are recorded in in-memory status, never credentials or message
bodies.

## Capacity and cost boundaries

The reference relay is single-process/sequential with five-second socket timeout;
120 authenticated requests/minute/role, 4 KiB text/message, 32 KiB HTTP body (including JSON escaping),
50 inbox messages/pass, 4,096 rows (2,048 per direction, reserving receipt capacity) and SQLite's 8,192-page cap (~32 MiB at default
page size). Expired IDs remain for a further 24 hours to stop replay, then are
pruned on new writes. A full queue fails instead of silently dropping an accepted
message. Acknowledgements stop redelivery; expired content remains until pruning.
Browser localStorage is limited by the browser as well as the 50-message app cap.
Polling is active only while the foreground bridge or explicitly opted-in desktop is running; the bridge has a ten-second socket timeout and a
2 MiB response cap covering 50 maximally escaped valid messages.

Self-hosting needs an already-available, secure, publicly reachable machine and
can carry electricity/network/domain costs. No-paid-dependency source does not guarantee free
hosting forever. A possible later port is Cloudflare Workers Free with SQLite
Durable Objects, whose current published free quotas fail at the free limit;
this Python relay does **not** run unchanged on Workers. No Cloudflare deployment
template is claimed, and provider accounts/terms/limits must be reviewed at setup:
https://developers.cloudflare.com/durable-objects/platform/pricing/

## Protocol v1

All API calls require `Authorization: Bearer <role-token>`; tokens never appear
in query strings. The static shell is public and contains no personal data.
No CORS access is enabled. API bodies/responses use JSON and are not cached.

- `POST /v1/messages`: exactly `{id, body, expires}`. `id` is 32 lowercase hex
  digits; `expires` is a finite Unix timestamp in the next 24 hours. Same role/ID/
  body/expiry is idempotent; changed replay returns 409. Companion posts prompts;
  workstation posts delivery notices. The same ID can exist in each direction.
- `GET /v1/inbox`: returns `{messages: [{id, body, expires}]}` for the other role,
  never one's own outgoing messages.
- `POST /v1/ack`: exactly `{id}`; only the recipient can acknowledge.
- 401: invalid/expired pairing; 413: body too large; 429: rate limit;
  507: queue capacity reached; retry transient failures without changing IDs.

The owner label is bound to the SQLite database and never selected by request
input. Messages are rendered with `textContent`, not HTML. Service worker caching
covers only the public app shell, never authenticated API responses.

## License and dependencies

Project licensing is pending the owner’s choice; no new license grant is made.
Python 3.10+ standard library (PSF
License, SSL provided by the host Python/OpenSSL build), browser Web APIs and
SQLite bundled with Python (public domain) are its runtime components. No npm or
PyPI runtime packages are pinned because none are used. Keep the host Python,
OpenSSL and browser patched; the tested versions are in `VERIFICATION.md`.
