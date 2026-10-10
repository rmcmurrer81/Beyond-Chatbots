# Aster Android companion — offline source prototype

An Android Kotlin UI with a Java protocol model. **No APK/device run has been
verified yet. This does not call a phone or connect to the workstation.** The
foundation backend is CLI-only; NewBrain is not available, and there is no other
model/provider fallback.

## Current implementation

- Local demo invitation, optional standard Android notification, tap to return,
  explicit open-session action, dismiss/end, and honest unavailable voice state.
- Notification permission requested only after tapping the demo button. Denial
  leaves an in-app flow. No microphone permission or microphone code.
- HTTPS-origin format preview; it neither pairs nor connects or stores credentials.
- Owner-destination, bounded expiration, replay, single-pending-invitation and
  answer-once guards in a tested offline protocol model.
- No INTERNET permission, network implementation, FCM, WebRTC, phone provider,
  analytics, billing, background service, boot receiver, or full-screen intent.

No service fee is possible from this implementation. Building requires ordinary
free development tools; downloads may use metered data. Installing an APK and
allowing notifications are separate user actions. No installation was performed.

## Tests available now

JDK 17 or newer:

```sh
./scripts/test-contract.sh
```

These are executable pure-Java model tests, not Android UI, TLS, network, audio,
APK-build, or physical-phone tests. The Java `main` harness runs independently of
Gradle; `testDebugUnitTest` does not substitute for this command.

## Build when an Android development environment is available

Open this folder in Android Studio with JDK 17+ and Android SDK 35 / Build Tools
35.0.0. The project pins AGP 8.9.2, Kotlin 2.1.20, and expects Gradle 8.11.1.
There is no Gradle wrapper binary bundled in this initial source snapshot. With
Gradle 8.11.1 installed, use:

```sh
gradle :app:assembleDebug :app:lintDebug
```

The expected output, only after a successful build, is
`app/build/outputs/apk/debug/app-debug.apk`. Do not treat that path as an existing
artifact. SDK licenses must be reviewed/accepted by the user; no automatic license
acceptance script is supplied. No emulator download is needed for model tests.

## Secure transport contract for the next milestone

This is a design boundary, not an implemented or authenticated transport:

1. Remain off by default. Pairing requires a user-reviewed enrollment flow; no
   static/demo token may authorize a live connection.
2. Manually enroll the owner's device and workstation. Use OS-trusted HTTPS TLS,
   normal hostname verification, authenticated workstation identity, and scoped
   short-lived authorization. Never send credentials over HTTP/LAN plaintext,
   install a trust-all verifier, ignore certificate errors, or put secrets in URLs.
3. Invitation schema: unique `id` (1–80 ASCII letters/digits/hyphens), exact enrolled
   `destination`, Unix-seconds `issuedAt`, `expiresAt` (at most 60 seconds later).
   Authenticate before parsing/accepting. Check time skew and revocation; persist
   replay protection before acknowledgment, including across process restarts.
4. The model's in-memory owner `offline-demo-device` and replay set are demo-only.
   They provide no sender authentication and MUST NOT be reused as live enrollment.
   Its 1024-ID budget fails closed; production needs bounded durable expiry cleanup.
5. Show an invitation only for the enrolled owner. User answer authorizes opening
   that one session, not arbitrary future calls. Microphone activation additionally
   requires Android permission and an active answered session. Stop on end,
   revocation, disconnect, or expiry; no background listening.
6. Do not open firewall ports, start listeners, install persistent services, create
   API keys, or provision a relay automatically. Any future LAN prototype needs a
   separately reviewed TLS/listener setup; same Wi-Fi alone is not authentication.
7. A future Android voice adapter can use Core-Telecom and WebRTC. Same-Wi-Fi
   use can avoid service fees. Away-from-home reachability generally needs signaling
   and potentially TURN bandwidth; no claim of universally free reliable calling.
8. Keep reasoning, identity, and memory with Aster/NewBrain on the workstation.
   An awake, connected workstation is necessary. No fallback brain or canned
   simulated AI answer. Carrier calling is not implemented.

## Physical-device acceptance checklist (not yet run)

- Install a locally built APK only after user approval; verify application source.
- Allow and deny notification permission; demonstrate both UI paths.
- Create/open/dismiss; repeated taps; expired invite; rotate; restart; tap stale
  notification. A restart invalidates the invitation and cannot restart audio.
- Confirm no microphone indicator, network traffic, full-screen takeover or charges.
- Later live work requires separate TLS/auth, revocation/replay restart, screen-lock,
  Doze, Samsung battery settings, Wi-Fi/mobile transition and audio interruption tests.

## Primary implementation references

Checked 2026-10-04:
- https://developer.android.com/build/releases/agp-8-9-0-release-notes
- https://kotlinlang.org/docs/whatsnew2120.html
- https://developer.android.com/develop/connectivity/telecom/voip-app/telecom
- https://developer.android.com/about/versions/14/behavior-changes-14
- https://developer.android.com/develop/background-work/services/fgs/service-types
- https://firebase.google.com/docs/cloud-messaging/android-message-priority
- https://webrtc.org/getting-started/turn-server

## Away-from-home roadmap and zero-charge boundary

The requested end state includes a Samsung phone **and a laptop**, away from
home, receiving updates and sending messages/call invitations to the powered-on
workstation. This Android-only offline prototype is not that end state. A
cross-platform web/PWA client and outbound workstation relay adapter are the next
implementation; they must not expose the raw workstation API to the Internet.

A candidate is Cloudflare Workers **Free** with SQLite-backed Durable Objects and
WebSocket Hibernation. Official pricing checked 2026-10-04 lists 100,000 Durable
Object requests/day and 13,000 GB-s/day; operations exceeding free limits fail
rather than trigger paid overage while the account remains on Free. This can host
text/invitation signaling, not a blanket guarantee of free voice transport.
https://developers.cloudflare.com/durable-objects/platform/pricing/

Before live setup the user must approve the specific host/account, deployment,
and credential/enrollment flow. Stay on Free; no paid plan, payment method, custom
domain purchase, or TURN service is authorized. A free workers.dev address avoids
a domain purchase. Authenticate both ends; persistent sessions need expiration,
revocation, bounded message retention, and explicit personal-data sharing scope.
No account, token, pairing, deployment, or public listener was created here.

Browser/PWA tabs may sleep and cannot be promised to ring like cellular calls.
Background notification delivery needs its own permission and push implementation;
full two-way voice needs implemented and tested media transport and a ready
NewBrain speech path. Local reasoning can remain on the workstation, but relay
metadata/content privacy must be explained before enabling remote messaging.
