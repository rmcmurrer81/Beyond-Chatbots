# IdeaForge hands-free chat

Open IdeaForge normally, then click **Start Hands-Free** to opt into the
microphone. The female voice prefers Microsoft Zira Desktop. Only one Kira app
may hold the shared speech engine in the same Windows session: stop Humanoid
Researcher or BlueBook voice before starting IdeaForge voice.

Recognized final speech follows the same existing `IdeaForgeChat.ask` route as
typed questions. The app pauses recognition before the request, speaks the
answer, then resumes listening. Typed questions and project controls share the
same one-request guard. **Stop** invalidates the voice session immediately;
an answer already being generated may still appear in chat but cannot restart
speech. If device shutdown remains pending, Start waits for the original helper
to exit. Closing the window stops voice and the existing research manager.

**Mute AI voice** suppresses reply playback while leaving hands-free recognition
enabled. Voice is off by default, including after restart. Optional wake-phrase
settings in `ai/config.json` are respected without changing the request's case.
Spoken replies use a cleaned excerpt of at most 4,000 UTF-16 units; the full
answer remains visible. The speech feature saves no microphone audio or raw
transcript files. Ordinary chat/project records still use IdeaForge's existing
storage behavior.

## Setup

Install the normal app requirements and provide the configured local Ollama
model. The voice path does not need Faster-Whisper, pyttsx3 or sounddevice.
The old implementation is preserved but not loaded by the desktop app.

Build the fixed Windows speech helper explicitly once from the repository:

```bat
.venv\Scripts\python.exe -m kira_voice.build_windows_host --build
```

This uses the installed .NET Framework compiler and `System.Speech`; it creates
a source-hash-specific application under your LocalAppData/KiraVoiceHost.
The same exact helper may already be built by Humanoid Researcher or BlueBook.
An existing build is refused rather than overwritten. No alternative compiler,
execution-policy change or engine fallback is attempted after a failure.
The app reports a missing helper, recognizer, female voice, microphone or busy
speech engine and leaves typed chat available. See [backend details](../VOICE-BACKEND.md).

In an earlier developer test, the matching shared helper was built and its
microphone-init / female speech / resumed-listening / normal-exit cycle was
observed separately. That does not establish recognition accuracy, listening
quality or an IdeaForge model conversation. IdeaForge-specific integration
checks use injected chat and speech to validate routing and lifecycle.
