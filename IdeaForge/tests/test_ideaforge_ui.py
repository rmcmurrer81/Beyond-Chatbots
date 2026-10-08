"""Exercise the actual UI routing with injected Tk/chat/speech; no native devices."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import ideaforge
from ai.hands_free import voice_prompt


class Value:
    def __init__(self, value=None, **options): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Widget:
    def __init__(self, owner=None, **options):
        self.options, self.contents, self.bindings = dict(options), '', {}
        self.app = owner.app if owner is not None else self
        if owner is not None: self.app.widgets.append(self)
    def configure(self, **options): self.options.update(options)
    config = configure
    def __getitem__(self, key): return self.options[key]
    def pack(self, **options):
        self.pack_options = options; self.app.pack_order.append(self)
    def grid(self, **options): self.grid_options = options
    def columnconfigure(self, *args, **options): pass
    def pack_forget(self): pass
    def add(self, *args, **options): pass
    def heading(self, *args, **options): pass
    def column(self, *args, **options): pass
    def bind(self, event, callback): self.bindings[event] = callback
    def create_window(self, *args, **options): pass
    def bbox(self, *args): return (0, 0, 0, 0)
    def yview(self, *args): pass
    def set(self, *args): pass
    def get(self, *args): return self.contents
    def delete(self, *args): self.contents = ''
    def insert(self, position, text, **options): self.contents += text; return 'row'
    def see(self, *args): pass
    def selection(self): return []
    def get_children(self): return []
    def winfo_children(self): return []
    def destroy(self): pass


class App(Widget):
    def __init__(self, scenario):
        super().__init__()
        self.widgets, self.callbacks, self.protocols = [], [], {}
        self.pack_order = []
        self.scenario, self.closed = scenario, False
    def title(self, value): pass
    def geometry(self, value): pass
    def minsize(self, *args): pass
    def after(self, delay, callback): self.callbacks.append(callback)
    def protocol(self, event, callback): self.protocols[event] = callback
    def mainloop(self):
        try: self.scenario(self)
        finally: self.protocols['WM_DELETE_WINDOW']()
    def destroy(self): self.closed = True
    def button(self, text):
        return next(w for w in self.widgets if w.options.get('text') == text and 'command' in w.options)
    def click(self, text): self.button(text).options['command']()
    def pump(self): self.callbacks.pop(0)()
    def entry(self): return next(w for w in self.widgets if w.options.get('height') == 4)
    def text(self): return ''.join(w.contents for w in self.widgets)
    def bell(self): pass


class Chat:
    model_name = 'injected-model'
    current_project = current_project_name = None
    def __init__(self):
        self.requests, self.fail, self.stopped = [], False, False
        self.research_manager = SimpleNamespace(event_callback=None, shutdown=self.shutdown)
    def shutdown(self): self.stopped = True
    def ask(self, text, image_path=None):
        self.requests.append((text, image_path))
        if self.fail: raise RuntimeError('injected model failure')
        return 'Answer: ' + text


class Speech:
    def __init__(self, **options): self.options, self.calls, self.session = options, [], 7
    def start(self): self.calls.append('start'); return self.session
    def capabilities(self): return {'stt_available': None, 'tts_available': None}
    def pause(self): self.calls.append('pause'); return True
    def resume(self): self.calls.append('resume'); return True
    def speak(self, text): self.calls.append(('speak', text)); return True
    def stop(self): self.calls.append('stop')
    def close(self): self.calls.append('close'); return True
    def event(self, kind, **fields):
        self.options['on_event'](dict(type=kind, session=self.session, **fields))


class ActualUiRoutingTests(unittest.TestCase):
    def run_ui(self, scenario):
        self.chat, self.speech, self.workers = Chat(), [], []
        def speech_factory(**options):
            voice = Speech(**options); self.speech.append(voice); return voice
        class Thread:
            def __init__(inner, target, args=(), **options): inner.target, inner.args = target, args
            def start(inner): self.workers.append(inner)
        root = App(scenario)
        patches = [patch.object(ideaforge.tk, 'Tk', return_value=root),
                   patch.object(ideaforge.tk, 'Text', Widget),
                   patch.object(ideaforge.tk, 'Canvas', Widget),
                   patch.object(ideaforge.tk, 'BooleanVar', Value),
                   patch.object(ideaforge.tk, 'StringVar', Value),
                   patch.object(ideaforge, 'list_projects', return_value=[]),
                   patch.object(ideaforge.threading, 'Thread', Thread)]
        patches += [patch.object(ideaforge.ttk, name, Widget) for name in
                    ('Frame', 'Label', 'Button', 'Checkbutton', 'Panedwindow', 'Treeview', 'Scrollbar')]
        for item in patches: item.start()
        try: ideaforge.main(chat_factory=lambda:self.chat, controller_factory=speech_factory)
        finally:
            for item in reversed(patches): item.stop()
        self.assertTrue(root.closed)
        self.assertTrue(self.chat.stopped)
        return root

    def worker(self):
        worker = self.workers.pop(0)
        worker.target(*worker.args)

    def listen(self, app):
        app.click('Start Hands-Free')
        voice = self.speech[-1]
        voice.event('state', state='listening'); app.pump()
        return voice

    def test_primary_actions_reserve_space_and_toolbars_use_bounded_rows(self):
        def scenario(app):
            self.assertEqual(app.entry().options['width'], 1)
            self.assertEqual(app.button('Send').pack_options['side'], 'right')
            self.assertLess(app.pack_order.index(app.button('Send')), app.pack_order.index(app.entry()))
            self.assertEqual(app.button('Research').grid_options['column'], 1)
            self.assertEqual(app.button('Folder').grid_options['columnspan'], 2)
            self.assertEqual(app.button('Prototype').grid_options['row'], 1)
            self.assertEqual(app.button('Simulation').grid_options['column'], 2)
            self.assertEqual(app.button('Paste Screenshot').grid_options['column'], 1)
        self.run_ui(scenario)

    def test_idle_start_never_creates_speech_model_or_worker(self):
        def scenario(app):
            app.pump()
            self.assertEqual(self.speech, [])
            self.assertEqual(self.workers, [])
            self.assertEqual(self.chat.requests, [])
            self.assertEqual(app.button('Stop').options['state'], 'disabled')
        self.run_ui(scenario)

    def test_typed_send_enter_and_project_controls_share_one_guard(self):
        def scenario(app):
            entry = app.entry(); entry.contents = 'Explain a hinge'
            app.click('Send')
            entry.contents = 'Second request'
            entry.bindings['<Control-Return>'](None)
            app.click('Prototype')
            self.assertEqual(len(self.workers), 1)
            self.assertEqual(entry.contents, 'Second request')
            self.worker(); app.pump()
            self.assertEqual(self.chat.requests, [('Explain a hinge', None)])
            self.assertIn('Answer: Explain a hinge', app.text())
            self.assertEqual(self.speech, [])
        self.run_ui(scenario)

    def test_voice_uses_same_ask_pause_speak_and_resume_completion(self):
        def scenario(app):
            voice = self.listen(app)
            voice.event('transcript', text='Explain a hinge', final=True); app.pump()
            self.assertEqual(voice.calls, ['start', 'pause'])
            self.assertEqual(len(self.workers), 1)
            self.worker(); app.pump()
            self.assertEqual(self.chat.requests, [('Explain a hinge', None)])
            self.assertIn(('speak', 'Answer: Explain a hinge'), voice.calls)
            self.assertEqual(app.button('Send').options['state'], 'disabled')
            voice.event('transcript', text='Answer echo', final=True); app.pump()
            self.assertEqual(self.workers, [])
            voice.event('state', state='speaking'); voice.event('state', state='listening'); app.pump()
            self.assertEqual(app.button('Send').options['state'], 'normal')
        self.run_ui(scenario)

    def test_stop_while_thinking_keeps_answer_without_speaking(self):
        def scenario(app):
            voice = self.listen(app)
            voice.event('transcript', text='Question', final=True); app.pump()
            app.click('Stop')
            self.assertEqual(app.button('Start Hands-Free').options['state'], 'disabled')
            self.worker(); app.pump()
            self.assertIn('Answer: Question', app.text())
            self.assertFalse(any(type(c) is tuple and c[0] == 'speak' for c in voice.calls))
            self.assertNotIn('resume', voice.calls)
            self.assertEqual(app.button('Start Hands-Free').options['state'], 'normal')
        self.run_ui(scenario)

    def test_mute_resumes_input_without_speaking(self):
        def scenario(app):
            voice = self.listen(app)
            control = next(w for w in app.widgets if w.options.get('text') == 'Mute AI voice')
            control.options['variable'].set(True)
            voice.event('transcript', text='Question', final=True); app.pump()
            self.worker(); app.pump()
            self.assertIn('resume', voice.calls)
            self.assertFalse(any(type(c) is tuple and c[0] == 'speak' for c in voice.calls))
        self.run_ui(scenario)

    def test_chat_error_is_visible_and_resumes_only_enabled_voice(self):
        def scenario(app):
            voice = self.listen(app); self.chat.fail = True
            voice.event('transcript', text='Question', final=True); app.pump()
            self.worker(); app.pump()
            self.assertIn('injected model failure', app.text())
            self.assertIn('resume', voice.calls)
        self.run_ui(scenario)

    def test_close_invalidates_callback_before_late_chat_result(self):
        def scenario(app):
            voice = self.listen(app)
            voice.event('transcript', text='Question', final=True); app.pump()
            app.protocols['WM_DELETE_WINDOW']()
            old_text = app.text()
            self.worker()
            voice.event('transcript', text='Late', final=True)
            app.pump()
            self.assertEqual(app.text(), old_text)
            self.assertEqual(voice.calls.count('close'), 1)
            self.assertNotIn(('speak', 'Answer: Question'), voice.calls)
        self.run_ui(scenario)

    def test_optional_wake_phrase_preserves_request_and_requires_whole_phrase(self):
        config = {'require_wake_phrase': True, 'wake_phrase': 'IdeaForge'}
        self.assertEqual(voice_prompt('IDEAFORGE, Explain R2-D2', config), 'Explain R2-D2')
        self.assertIsNone(voice_prompt('AnotherIdeaForge question', config))
        self.assertIsNone(voice_prompt('IdeaForge!', config))
        self.assertIsNone(voice_prompt('Question', config))
        self.assertIsNone(voice_prompt('Question', {'require_wake_phrase': True, 'wake_phrase': ''}))
        self.assertEqual(voice_prompt('  R2-D2  ', {}), 'R2-D2')


if __name__ == '__main__': unittest.main()
