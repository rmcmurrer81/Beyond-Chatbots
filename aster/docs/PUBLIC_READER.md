# Anonymous static public reader

Aster can now read one explicitly selected public HTTP(S) source and follow a
numbered link selected from that exact in-memory source. This deterministic tool
needs only Python's standard library. It uses no browser, browser profile,
cookies, account, credentials, model or optional Chromium installation.

The separate default-browser handoff remains available and review-gated. It
never receives or opens retrieved links automatically. Starting Aster, checking
status, saving a prompt, receiving remote text and running queued research-link
jobs never initiate a public read.

## Desktop

The existing **Browser** tab remains the seventh tab:

1. Enter the exact public URL in the existing URL field.
2. Choose **Read public source**. This button requests one anonymous GET to that
   URL; no generic additional confirmation is needed for this bounded read.
3. Read the extracted title/text and provenance in the source pane. Choose one
   numbered destination in the link picker, review its complete URL, and choose
   **Follow selected link** to request only that destination.
4. **Cancel / clear source** invalidates the source and its links, and stops an
   active reader child. Editing the URL also invalidates the old source. Closing
   Aster cancels the reader. Cancellation is best effort once dispatch begins;
   it cannot undo a GET already sent.

Page content is inert, untrusted plain text. It can contain false claims or
instructions; Aster neither follows those instructions nor verifies the claims.
There is no HTML rendering, JavaScript, CSS layout or automatic subresource
loading. A link label is not proof that its destination is safe. Browser handoff
buttons still show their own review, including the possibility of existing
cookies or signed-in sessions in the user's default browser.

The pane shows the source URL, fetch timestamp, HTTP status, TLS verification,
body SHA-256 and truncation flags. A hash identifies the fetched body; it does
not prove authenticity or correctness. The source is not added to Aster's
persistent history, memory, research exports or queue.

## CLI

```sh
python -m aster.browser_public status
python -m aster.browser_public read --url "https://docs.python.org/3/"
python -m aster.browser_public session --url "https://docs.python.org/3/"
```

`read` performs one request and prints its bounded JSON result. `session` keeps
one navigation in memory and accepts these exact commands:

- `follow N`: request numbered link N from the current snapshot
- `read`: print the cached source without making another request
- `clear`: discard the source and link selection
- `quit`: close and discard the session

A new explicit CLI `read` or a new desktop **Read public source** refreshes a
source. There is no implicit refresh, saved navigation session, automatic retry,
redirect traversal or persistent permission. Invalid session commands invalidate
the current source. The CLI creates no Aster state directory, account, profile,
credential file or page-body log. Normal Python bytecode caching can be disabled
with `python -B` if desired. One-shot failed/unsupported reads return exit code 2;
read and displayed-redirect results return 0.

## Outcomes and limits

- `read`: an inert static HTML or plain-text response was extracted. It is not a
  rendered browser page or proof that its claims are trustworthy.
- `redirect`: the redirect was not followed. An eligible destination is exposed
  as one selectable link; an ineligible destination yields no link.
- `unsupported`: the response cannot be safely read by this version, for example
  compressed/chunked framing, an attachment, unsupported media or encoding.
- `failed`: a bounded static reason describes the refusal or failure. Raw OS,
  transport exceptions, child stderr and environment data are never displayed.

Each explicit read starts a navigation lasting at most 15 minutes and 32 total
read/follow operations. Sources and links have unpredictable, instance-owned
IDs. New requests, invalid follow attempts, failures, source changes and clear
consume the old snapshot, so old IDs cannot authorize new requests. At most five
consecutive redirect destinations can be explicitly followed, with cycle checks.
Restarting or constructing another session does not replay any request.

Transport constraints:

- Public IPv4 only, HTTP port 80 or HTTPS port 443. IPv6, loopback, private,
  link-local, reserved, cloud platform and special-purpose addresses are denied.
  Local/special-use names and ambiguous host encodings are denied.
- DNS is resolved once per request; every returned A address must be public.
  The socket connects to the chosen numeric peer, which is checked. HTTPS checks
  the original hostname with certificate verification. There is no insecure-TLS
  switch, alternate proxy, private-network bypass or custom network setting.
  This public-IP filtering is application policy on a trusted host/network,
  not an OS egress firewall: it cannot rule out local NAT or routing to
  globally numbered internal services.
- Credential-like URL parameters and user-info URLs are denied. This is not
  general secret detection: never paste private data into a URL. An anonymous
  GET still discloses the URL and reader's network address to the destination;
  a server can retain its own logs or have side effects even for GET.
- No auth headers, cookies, referer, proxy, request body, credential cache,
  login/account creation, forms, uploads or downloads. No browser reuse.
- At most 1 MiB response body and 1 MiB + 64 KiB of HTTP-response bytes after
  TLS decoding (not DNS/TCP/TLS packet overhead), 32 KiB/65 header lines,
  8 KiB per line, 12,000 extracted text characters, 256 title characters and
  32 links, each with at most 4,096 URL and 160 label characters.

## Disposable worker boundary

Only a fixed reviewed `aster/public_worker.py` child calls the transport in
production. The supervisor invokes the current Python executable with `-I -B`,
no shell and no caller-supplied executable, script or options. Bounded JSON stdin
contains only the selected URL. The child receives an empty environment on
POSIX; Windows retains only its OS-directory variables. Proxy, Python, browser,
credential and SSL environment overrides are not inherited. TLS loads compiled
CA paths or Windows system roots, never a user-selected certificate path or TLS
key log.

A 20-second supervisor request deadline covers DNS, connection, response and
parsing. Individual transport operations have a five-second bound after DNS.
The parent reads at most 512 KiB of child output, validates its exact schema,
URLs, text limits, metadata and static reasons, and discards stderr. Display
metadata cannot contain control characters, and timestamps must use the exact
UTC ISO format emitted by the transport (with `T` and `+00:00`). On timeout,
cancellation or oversized output it kills and reaps the child without retry.
Cleanup can take normal OS scheduling time. This is not hard OS memory/CPU or
filesystem isolation; no claim of a general hostile-code sandbox is made.

## Verification

`tests/test_browser_public.py` uses offline fixtures and mocked transport at the
private supervisor boundary. No public test URL, real user browser, account or
profile is contacted by these tests. Coverage includes bounded/bad output,
worker deadline and cleanup, environment filtering, schema validation, owned
link IDs, stale/replayed/concurrent requests, TTL/operation limits, redirect
cycles, CLI state absence, inert prompts/remote text/queues, and actual Tk
read/follow/cancel/source-change/repeat/error/close controls.

Native Tk requires a graphical session. Its test fails on Windows if Tk is
unavailable; headless Linux records an explicit skip, which does not qualify
native UI. Public Internet smoke and native qualification are separate gates;
passing offline tests alone does not prove either one works. See the compact
public-reader check results for the exact source hashes and actual outcomes.
