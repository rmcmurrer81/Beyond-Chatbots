# Explicit default-browser actions

Aster can hand an exact, owner-reviewed HTTP(S) website, source URL, or encoded
Google search to the operating system's default browser. This is a deterministic
local tool; it does not require or activate a model.

The separate [anonymous public reader](PUBLIC_READER.md) adds static read/follow
controls to the same tab. It does not change this handoff or open links for you.

## Desktop

Open Aster, choose **Browser**, and type a public URL or the exact search words.
Choose **Review website**, **Review source URL**, or **Review Google search**.
The separate confirmation shows the complete destination. Cancel or close the
review to do nothing. Confirm once to request the handoff.

Source mode deliberately makes no claim that Aster has verified a publisher or
read a source. It accepts a source URL the owner has checked, validates its URL
syntax, and shows the exact URL again before opening. Research exports, page
text, stored memories, and pending prompts are never auto-opened or appended to
searches. Search sends only the exact text typed to Google.

## CLI

Preview without launching or opening Aster's private state:

```sh
python -m aster browser status
python -m aster browser url "https://example.com/"
python -m aster browser source "https://docs.python.org/3/library/os.html"
python -m aster browser search "compliant robot gripper"
```

Review the `url` and warnings in the result. To open, repeat that exact command
with `--approve --plan-sha256 SHA_FROM_PREVIEW`:

```sh
python -m aster browser url "https://example.com/" --approve --plan-sha256 SHA_FROM_PREVIEW
```

The hash binds the mode and complete normalized destination. A changed URL or
search requires a new preview. The CLI does not save a reusable grant. Repeating
an approved CLI command is a fresh explicit request and can open another tab.
Quote values correctly for the shell you use. No command typed inside a search
or URL is evaluated by Aster.

## Outcomes

- `review_required`: nothing has launched.
- `launch_requested`: the OS accepted the handoff. This does not prove that the
  browser displayed the page, that Internet connectivity exists, or that the
  destination is trustworthy.
- `launch_failed`: no success was reported by the platform adapter. Check the
  graphical session, browser installation, and default URL association.
- `launch_unknown`: the platform launcher timed out. A browser may already be
  open; check before explicitly retrying. Aster never retries automatically.

CLI failure and uncertain launch outcomes return exit code 2. The desktop shows
the outcome in the Browser panel. It does not falsely say a page was loaded when
offline or when the launcher merely accepted a request.

## Boundaries

- Only absolute HTTP and HTTPS URLs. No `file:`, `javascript:`, custom app
  protocols, executable paths, shell strings, or browser command options.
- Conservative syntax: a maximum 4,096-character ASCII URL; Unicode URL content
  must be percent-encoded (IDN hosts use their ASCII form). Search text may be
  Unicode and is limited to 1,000 characters. Controls, invisible characters,
  malformed escapes, encoded controls, and structural URL backslashes are
  rejected. Literal backslashes in an explicitly typed search are safely encoded.
- User-info credentials and common credential/signed-login query or fragment
  parameters are rejected. This is not general secret detection. Do not paste
  secrets into URLs or search boxes. URL paths and arbitrary search text can
  still contain private information the software cannot recognize.
- Windows uses the OS `startfile(url, 'open')` HTTP(S) association. Linux uses
  fixed `/usr/bin/xdg-open` with a graphical session. macOS uses fixed
  `/usr/bin/open`; its adapter is covered by mocks, not native qualification.
  POSIX adapters pass an argument list with `shell=False`; no PATH search or
  `BROWSER` environment override is used.
- The browser is outside Aster's control. It may send cookies, use an existing
  login, fetch subresources, follow redirects, show downloads, or display a
  page with side effects. Review the destination first. Aster does not attach
  to that profile, grant itself access, or inspect its contents.
- This handoff does not read webpages, click links, fill forms, sign in, create
  accounts, verify web claims, or provide background browsing. The separate
  public reader extracts anonymous static text only; it is not browser control.
- There is no prompt-to-tool dispatcher or durable browser job. GUI approval
  tickets are in-memory, exact, single-use and consumed even after failure.
  Opening/restarting Aster, remote text, queued research links, or reconnecting
  the network never launches a browser. No URL/query is persisted merely by
  previewing or launching.
- Production NewBrain remains unavailable; no Qwen or other fallback is added.

## Verification

All browser launches in automated opener tests are mocked, including Windows
`startfile`. Tests cover URL rejection, encoded query integrity, no private
context augmentation, launch errors/timeouts, offline uncertainty, CLI exits,
one-use confirmations, cancellation, duplicate submission, and restart safety.
Native Tk interaction runs when a display exists; Windows CI treats a missing
native UI as a failure. A headless Linux skip does not qualify the UI.

The existing aggregate command includes these tests and preserves outcomes:

```sh
python -B scripts/record_upgrade_checks.py --output NEW_EVIDENCE_DIRECTORY
```

The October 6 implementation records are under
[`test-results/browser-actions/`](../test-results/browser-actions/). These tests
do not qualify the owner's installed browser, physical workstation, Internet
connection, or a live website. No user browser was opened during development.

Platform references:
[Python os.startfile](https://docs.python.org/3/library/os.html#os.startfile),
[Python subprocess security](https://docs.python.org/3/library/subprocess.html#security-considerations).
