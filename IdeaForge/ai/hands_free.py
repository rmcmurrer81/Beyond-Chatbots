from __future__ import annotations
import queue, threading
from collections.abc import Mapping
import re


def voice_prompt(text, config):
    """Optional wake phrase; preserve the case and wording of the user's request."""
    if not config.get("require_wake_phrase", False):
        return text.strip()
    wake = config.get("wake_phrase", "IdeaForge")
    if type(wake) is not str or not wake.strip():
        return None
    match = re.search(r"(?<!\w)" + re.escape(wake.strip()) + r"(?!\w)", text, re.IGNORECASE)
    return text[match.end():].strip(" ,.!?\t\r\n") or None if match else None


def _voice_controller(**kwargs):
    from kira_voice import VoiceController
    return VoiceController(**kwargs)


def speech_excerpt(text):
    """Keep the displayed reply intact; bound only the spoken UTF-16 text."""
    spoken, units, changed = [], 0, False
    for character in text:
        if ord(character) < 32 and character not in "\r\n\t" or 0xD800 <= ord(character) <= 0xDFFF:
            character, changed = " ", True
        width = 2 if ord(character) > 0xFFFF else 1
        if units + width > 4000:
            changed = True
            break
        spoken.append(character)
        units += width
    return "".join(spoken), changed


VOICE_ERRORS = {
    "recognizer_unavailable": "No installed en-US speech recognizer is available.",
    "female_voice_unavailable": "No installed female Windows voice is available.",
    "microphone_unavailable": "Microphone unavailable. Check the Windows input device and microphone permission.",
    "speech_busy_other_app": "Voice is active in another Kira app. Stop it there before starting here.",
    "transcript_too_long": "That utterance exceeded the speech limit. Try a shorter question.",
    "invalid_speech_text": "The voice backend rejected the spoken text.",
    "speech_failed": "The voice backend could not finish speaking.",
    "speech_already_pending": "The voice backend already has speech pending.",
    "command_queue_full": "The voice command queue is full.",
    "speech_host_unavailable": "The Windows speech host is unavailable.",
    "windows_speech_framework_unavailable": "Windows System.Speech is unavailable.",
}


class HandsFreeChat:
    """Tk-thread lifecycle; backend callbacks only enqueue original events.

    A fresh controller per Start and its returned session invalidate old
    callbacks. This helper needs no Tk, microphone, TTS or ChatSession.
    """
    def __init__(self, enqueue, on_prompt, on_change, on_problem,
                 controller_factory=_voice_controller):
        self.enqueue, self.on_prompt = enqueue, on_prompt
        self.on_change, self.on_problem = on_change, on_problem
        self.controller_factory = controller_factory
        self.controller = None
        self.retiring = None
        self.enabled = self.closed = self.busy = False
        self.state = "off"
        self.generation = self.turn_number = 0
        self.session = self.current_turn = self.last_transcript_event = None
        self.awaiting_speech = False
        self.speech_started = False
        self.voice_label = "Voice: installed generic female System.Speech voice (not checked)"

    @property
    def blocked(self):
        return self.closed or self.busy or self.awaiting_speech or self.state == "speaking"

    @property
    def start_blocked(self):
        return self.blocked or self.retiring is not None

    def poll_retirement(self):
        if self.closed or self.retiring is None:
            return
        try:
            status = self.retiring.status()
            if status.get("process_running") is False and status.get("pending_stop") is False:
                self.retiring = None
                self._changed()
        except Exception:
            pass  # Unknown retirement remains pending; never launch over it.

    def _changed(self):
        if not self.closed:
            self.on_change()

    def _problem(self, message):
        if not self.closed:
            self.on_problem(message)

    def _capabilities(self, event):
        name = event.get("voice_name")
        if type(name) is str and name:
            self.voice_label = f"Voice: {name} (installed generic female System.Speech)"
        if event.get("stt_available") is False or event.get("tts_available") is False:
            reason = event.get("reason")
            self.stop()
            self._problem(reason if type(reason) is str and reason else "Required Windows voice capability is unavailable.")

    def start(self):
        self.poll_retirement()
        if self.start_blocked or self.enabled:
            return False
        self.generation += 1
        generation = self.generation
        self.last_transcript_event = None

        def receive(event):
            if not self.closed:
                self.enqueue(("voice", (generation, event)))

        try:
            self.controller = self.controller_factory(
                on_event=receive, culture="en-US", voice_name=None,
                tts_backend="system_speech", process_factory=None)
            self.enabled = True
            self.state = "off"
            self.session = self.controller.start()
            if type(self.session) is not int:
                raise RuntimeError("Voice backend did not return its session.")
            capabilities = self.controller.capabilities()
            if isinstance(capabilities, Mapping):
                self._capabilities(capabilities)
        except Exception as error:
            self.stop()
            self._problem(f"Hands-free is unavailable: {error}")
            return False
        self._changed()
        return self.enabled

    def stop(self):
        controller, self.controller = self.controller, None
        self.enabled = False
        self.generation += 1
        self.session = None
        self.state = "off"
        self.awaiting_speech = False
        self.speech_started = False
        # Existing chat work remains busy until its original worker returns.
        if controller is not None:
            try: controller.stop()
            except Exception as error: self._problem(f"Voice shutdown: {error}")
            try:
                if controller.close() is False:
                    self.retiring = controller
                    self._problem("Voice shutdown is pending; Start waits for the original host to exit.")
            except Exception as error:
                self.retiring = controller
                self._problem(f"Voice shutdown is pending: {error}")
        self._changed()

    def close(self):
        if not self.closed:
            self.closed = True
            self.stop()

    def begin_turn(self):
        if self.blocked:
            return None
        self.turn_number += 1
        token = (self.turn_number, self.generation if self.enabled else None)
        self.current_turn, self.busy = token, True
        if self.enabled:
            try:
                if self.controller.pause() is False:
                    raise RuntimeError("Voice backend refused the pause command.")
                self.state = "thinking"
            except Exception as error:
                self.stop()
                self.current_turn, self.busy = None, False
                self._problem(f"Could not pause voice input: {error}")
                self._changed()
                return None
        self._changed()
        return token

    def _resume(self):
        if self.enabled and not self.closed and not self.busy:
            try:
                if self.controller.resume() is False:
                    raise RuntimeError("Voice backend refused the resume command.")
            except Exception as error:
                self.stop()
                self._problem(f"Could not resume voice input: {error}")

    def finish_turn(self, token, kind, text=""):
        if self.closed or self.current_turn is None or token != self.current_turn:
            return False
        self.current_turn, self.busy = None, False
        if self.enabled and token[1] == self.generation:
            if kind == "answer" and type(text) is str and text.strip():
                spoken, changed = speech_excerpt(text)
                if changed:
                    self._problem("Voice reads a bounded, cleaned excerpt (up to 4,000 characters); the full reply remains in chat.")
                if not spoken.strip():
                    self._resume()
                    self._changed()
                    return True
                self.awaiting_speech, self.state = True, "speaking"
                self.speech_started = False
                try:
                    if self.controller.speak(spoken) is False:
                        self.awaiting_speech, self.state = False, "thinking"
                        self._problem("The voice backend did not accept this reply for speech.")
                        self._resume()
                    # Backend resumes recognition after current TTS completes.
                except Exception as error:
                    self.stop()
                    self._problem(f"Could not speak the answer: {error}")
            else:
                self._resume()  # Chat error, cancelled Learn, or no reply.
        self._changed()
        return True

    def handle_event(self, generation, event):
        if (self.closed or not self.enabled or generation != self.generation
                or not isinstance(event, Mapping) or event.get("session") != self.session):
            return
        kind = event.get("type")
        if kind == "capabilities":
            self._capabilities(event)
        elif kind == "state":
            state = event.get("state")
            if state not in ("off", "listening", "thinking", "speaking"):
                return
            if self.busy:
                self.state = "thinking"
            elif self.awaiting_speech:
                if state == "listening" and self.speech_started:
                    self.awaiting_speech, self.state = False, "listening"
                elif state == "speaking":
                    self.state = "speaking"
                    self.speech_started = True
                # Queued pause/thinking never resumes or ends an utterance.
            else:
                self.state = state
        elif kind == "error":
            message = event.get("message")
            code = event.get("code")
            self._problem(message if type(message) is str else VOICE_ERRORS.get(
                code, f"Voice error: {code}" if type(code) is str else "Voice input or capability error."))
            if event.get("fatal") is True:
                self.stop()
            elif not self.busy and (self.awaiting_speech or code == "transcript_too_long"):
                self.awaiting_speech = False
                self.speech_started = False
                if code != "speech_already_pending": self.state = "thinking"
                self._resume()
        elif kind == "transcript":
            text = event.get("text")
            if (self.blocked or self.state != "listening" or event.get("final") is not True
                    or type(text) is not str or not 0 < len(text.strip()) <= 4000
                    or event is self.last_transcript_event):
                return
            self.last_transcript_event = event
            token = self.begin_turn()
            if token is not None:
                self.on_prompt(text.strip(), token)
        self._changed()

