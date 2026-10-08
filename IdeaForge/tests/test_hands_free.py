"""Injected GUI lifecycle tests: no Tk, native voice, microphone or model."""
import queue
import threading
import unittest
from types import MappingProxyType

from ai.hands_free import HandsFreeChat, speech_excerpt


class FakeVoice:
    def __init__(self, owner, **options):
        self.owner, self.options = owner, options
        self.callback = options["on_event"]
        self.session = 7
        self.fail = None
        self.pending = False
        self.capability = {"voice_name": "Installed Female Test Voice",
                           "stt_available": None, "tts_available": None}

    def start(self):
        self.owner.append("start")
        return self.session

    def capabilities(self):
        return MappingProxyType(self.capability)

    def pause(self):
        self.owner.append("pause")
        if self.fail == "pause":
            raise RuntimeError("pause failed")
        return self.fail != "pause_false"

    def resume(self):
        self.owner.append("resume")
        if self.fail == "resume":
            raise RuntimeError("resume failed")
        return self.fail != "resume_false"

    def speak(self, text):
        if len(text) > 4000 or len(text.encode("utf-16-le")) // 2 > 4000:
            raise ValueError("speech text too long")
        if any(ord(character) < 32 and character not in "\r\n\t" for character in text):
            raise ValueError("unsupported controls")
        self.owner.append(("speak", text))
        if self.fail == "speak":
            raise RuntimeError("speak failed")
        return self.fail != "speak_false"

    def stop(self):
        self.owner.append("stop")
        if self.fail == "stop":
            raise RuntimeError("stop failed")

    def close(self):
        self.owner.append("close")
        return not self.pending

    def status(self):
        return {"process_running": self.pending, "pending_stop": self.pending}

    def event(self, kind, **fields):
        return MappingProxyType(dict(type=kind, session=self.session, **fields))


class VoiceGuiTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.requests, self.problems, self.changes = [], [], [], []
        self.events = queue.Queue()
        self.instances = []

        def factory(**options):
            controller = FakeVoice(self.calls, **options)
            self.instances.append(controller)
            return controller

        def prompt(text, token):
            self.calls.append(("ask", text))
            self.requests.append((text, token))

        self.gui = HandsFreeChat(self.events.put, prompt,
                                 lambda: self.changes.append(threading.get_ident()),
                                 self.problems.append, factory)

    def listen(self):
        self.assertTrue(self.gui.start())
        self.voice = self.instances[-1]
        self.deliver("state", state="listening")

    def deliver(self, kind, **fields):
        event = self.voice.event(kind, **fields)
        self.gui.handle_event(self.gui.generation, event)
        return event

    def question(self):
        self.listen()
        self.deliver("transcript", text="Explain the knee", final=True, confidence=0.9)
        return self.requests[-1][1]

    def test_off_default_has_no_backend_or_audio_acquisition(self):
        self.assertFalse(self.gui.enabled)
        self.assertEqual(self.gui.state, "off")
        self.assertEqual(self.instances, [])
        token = self.gui.begin_turn()
        self.assertTrue(self.gui.finish_turn(token, "answer", "Typed answer"))
        self.assertEqual(self.calls, [])

    def test_start_uses_exact_backend_options_and_returned_session(self):
        self.listen()
        self.assertEqual(self.gui.session, 7)
        self.assertEqual(self.voice.options["culture"], "en-US")
        self.assertIsNone(self.voice.options["voice_name"])
        self.assertIsNone(self.voice.options["process_factory"])
        self.assertEqual(self.voice.options["tts_backend"], "system_speech")
        self.assertIn("Installed Female Test Voice", self.gui.voice_label)

    def test_callback_on_background_thread_only_queues_original_event(self):
        self.listen()
        self.changes.clear()
        event = self.voice.event("transcript", text="Question", final=True)
        thread = threading.Thread(target=lambda: self.voice.callback(event))
        thread.start(); thread.join()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.changes, [])
        kind, (generation, original) = self.events.get_nowait()
        self.assertEqual(kind, "voice")
        self.assertIs(original, event)
        self.gui.handle_event(generation, original)
        self.assertEqual(len(self.requests), 1)

    def test_voice_prompt_pauses_before_exactly_one_existing_chat_request(self):
        self.listen()
        event = self.deliver("transcript", text="  Explain the knee  ", final=True)
        self.gui.handle_event(self.gui.generation, event)
        self.deliver("transcript", text="Another question", final=True)
        self.assertEqual(self.requests[0][0], "Explain the knee")
        self.assertEqual(len(self.requests), 1)
        self.assertLess(self.calls.index("pause"), self.calls.index(("ask", "Explain the knee")))
        self.assertIsNone(self.gui.begin_turn())  # Ctrl-Return and Learn share this guard.

    def test_partial_empty_oversize_and_wrong_session_transcripts_are_ignored(self):
        self.listen()
        for fields in ({"text": "Partial", "final": False},
                       {"text": " ", "final": True},
                       {"text": "x" * 4001, "final": True}):
            self.deliver("transcript", **fields)
        self.gui.handle_event(self.gui.generation,
                              MappingProxyType({"type": "transcript", "session": 8,
                                                "text": "Wrong", "final": True}))
        self.assertEqual(self.requests, [])

    def test_answer_speaks_once_and_blocks_echo_until_backend_completion(self):
        token = self.question()
        self.assertTrue(self.gui.finish_turn(token, "answer", "Answer"))
        self.assertFalse(self.gui.finish_turn(token, "answer", "Duplicate"))
        self.assertEqual(self.calls.count(("speak", "Answer")), 1)
        self.deliver("state", state="thinking")  # Old pause event.
        self.deliver("state", state="listening")  # Queued pre-TTS state is insufficient.
        self.assertTrue(self.gui.blocked)
        self.deliver("transcript", text="Answer echo", final=True)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("resume", self.calls)
        self.deliver("state", state="speaking")
        self.deliver("state", state="listening")
        self.assertFalse(self.gui.blocked)
        self.deliver("transcript", text="Next question", final=True)
        self.assertEqual(len(self.requests), 2)

    def test_long_answer_speaks_bounded_excerpt_and_preserves_full_display_return(self):
        token = self.question()
        full_answer = "a" * 5000
        self.assertTrue(self.gui.finish_turn(token, "answer", full_answer))
        self.assertIn(("speak", "a" * 4000), self.calls)
        self.assertTrue(self.gui.enabled)
        self.assertTrue(any("full reply remains in chat" in message for message in self.problems))
        self.assertEqual(len(full_answer), 5000)

    def test_spoken_controls_are_cleaned_and_utf16_limit_is_respected(self):
        spoken, changed = speech_excerpt("before\x00after\x01\n" + "\U0001f600" * 2500)
        self.assertTrue(changed)
        self.assertTrue(spoken.startswith("before after \n"))
        self.assertLessEqual(len(spoken.encode("utf-16-le")) // 2, 4000)
        token = self.question()
        self.gui.finish_turn(token, "answer", "Answer\x00text")
        self.assertIn(("speak", "Answer text"), self.calls)
        self.assertTrue(self.gui.enabled)

    def test_nonfatal_speech_error_before_speaking_event_resumes_current_session(self):
        token = self.question()
        self.gui.finish_turn(token, "answer", "Answer")
        self.deliver("error", code="invalid_speech_text", fatal=False)
        self.assertFalse(self.gui.awaiting_speech)
        self.assertEqual(self.calls.count("resume"), 1)
        self.assertTrue(self.gui.enabled)
        self.assertIn("The voice backend rejected the spoken text.", self.problems)

    def test_false_pause_refuses_chat_and_false_speak_does_not_stick(self):
        self.listen()
        self.voice.fail = "pause_false"
        self.deliver("transcript", text="Question", final=True)
        self.assertEqual(self.requests, [])
        self.assertFalse(self.gui.enabled)
        self.listen()
        self.deliver("transcript", text="Question", final=True)
        token = self.requests[-1][1]
        self.voice.fail = "speak_false"
        self.gui.finish_turn(token, "answer", "Answer")
        self.assertFalse(self.gui.awaiting_speech)
        self.assertIn("resume", self.calls)

    def test_pending_close_blocks_new_voice_host_until_original_status_retires(self):
        self.listen()
        original = self.voice
        original.pending = True
        self.gui.stop()
        self.assertIs(self.gui.retiring, original)
        self.assertFalse(self.gui.start())
        self.assertEqual(len(self.instances), 1)
        self.assertTrue(any("shutdown is pending" in message for message in self.problems))
        original.pending = False
        self.gui.poll_retirement()
        self.assertIsNone(self.gui.retiring)
        self.assertTrue(self.gui.start())
        self.assertEqual(len(self.instances), 2)

    def test_stop_before_answer_never_speaks_or_resumes_and_keeps_chat_busy(self):
        token = self.question()
        self.gui.stop()
        self.assertTrue(self.gui.busy)
        self.assertFalse(self.gui.start())
        self.assertIsNone(self.gui.begin_turn())
        self.assertTrue(self.gui.finish_turn(token, "answer", "Late answer"))
        self.assertFalse(self.gui.busy)
        self.assertNotIn(("speak", "Late answer"), self.calls)
        self.assertNotIn("resume", self.calls)

    def test_stop_and_restart_ignores_old_generation_even_same_backend_session(self):
        self.listen()
        old = self.voice
        generation = self.gui.generation
        self.gui.stop()
        self.assertTrue(self.gui.start())
        self.voice = self.instances[-1]
        self.deliver("state", state="listening")
        old.callback(old.event("transcript", text="Old event", final=True))
        kind, payload = self.events.get_nowait()
        self.assertEqual(kind, "voice")
        self.assertEqual(payload[0], generation)
        self.gui.handle_event(*payload)
        self.assertEqual(self.requests, [])
        self.assertIsNot(old, self.voice)

    def test_chat_error_and_empty_answer_resume_only_current_enabled_session(self):
        token = self.question()
        self.assertTrue(self.gui.finish_turn(token, "error", "Chat failed"))
        self.assertEqual(self.calls.count("resume"), 1)
        self.deliver("state", state="listening")
        token = self.gui.begin_turn()
        self.assertTrue(self.gui.finish_turn(token, "answer", ""))
        self.assertEqual(self.calls.count("resume"), 2)

    def test_learn_cancel_and_result_preserve_serialization_without_tts(self):
        self.listen()
        token = self.gui.begin_turn()
        self.deliver("transcript", text="During modal dialog", final=True)
        self.assertEqual(self.requests, [])
        self.gui.finish_turn(token, "cancelled")
        self.assertEqual(self.calls.count("resume"), 1)
        token = self.gui.begin_turn()
        self.gui.finish_turn(token, "learned", "Saved topic")
        self.assertEqual(self.calls.count("resume"), 2)
        self.assertFalse(any(type(call) is tuple and call[0] == "speak" for call in self.calls))

    def test_pause_failure_stops_voice_and_does_not_dispatch_chat(self):
        self.listen()
        self.voice.fail = "pause"
        self.deliver("transcript", text="Question", final=True)
        self.assertEqual(self.requests, [])
        self.assertFalse(self.gui.enabled)
        self.assertFalse(self.gui.busy)
        self.assertIn("close", self.calls)
        self.assertTrue(self.problems)

    def test_speak_failure_disables_voice_without_restarting_microphone(self):
        token = self.question()
        self.voice.fail = "speak"
        self.gui.finish_turn(token, "answer", "Answer")
        self.assertFalse(self.gui.enabled)
        self.assertNotIn("resume", self.calls)
        self.assertTrue(self.problems)

    def test_resume_failure_disables_voice(self):
        token = self.question()
        self.voice.fail = "resume"
        self.gui.finish_turn(token, "error", "Chat error")
        self.assertFalse(self.gui.enabled)
        self.assertIn("close", self.calls)

    def test_capability_failure_is_visible_and_disables_handsfree(self):
        self.listen()
        self.deliver("capabilities", stt_available=False, tts_available=True,
                     reason="No installed recognizer")
        self.assertFalse(self.gui.enabled)
        self.assertIn("No installed recognizer", self.problems)

    def test_fatal_error_disables_handsfree_and_old_errors_are_ignored(self):
        self.listen()
        generation = self.gui.generation
        self.deliver("error", message="Voice process failed", fatal=True)
        self.assertFalse(self.gui.enabled)
        count = len(self.problems)
        self.gui.handle_event(generation, self.voice.event("error", message="Old", fatal=True))
        self.assertEqual(len(self.problems), count)

    def test_close_is_cooperative_idempotent_and_suppresses_all_late_ui_work(self):
        token = self.question()
        self.voice.fail = "stop"
        self.gui.close()
        changes, problems = len(self.changes), len(self.problems)
        self.voice.callback(self.voice.event("transcript", text="Late", final=True))
        self.gui.handle_event(self.gui.generation, self.voice.event("state", state="listening"))
        self.assertFalse(self.gui.finish_turn(token, "answer", "Late"))
        self.gui.close()
        self.assertEqual(len(self.changes), changes)
        self.assertEqual(len(self.problems), problems)
        self.assertTrue(self.events.empty())
        self.assertEqual(self.calls.count("close"), 1)


if __name__ == "__main__":
    unittest.main()
