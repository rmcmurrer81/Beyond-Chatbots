"""Portable actual-source ID/UI regressions; only fresh synthetic project data.

Place in repo/tests. Tk, chat, speech, project-state and worker threads are
injected before loading the actual main module. No Tk/native/model/service call.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


projects = load_source('_id_test_projects', REPO / 'core/projects.py')
index = load_source('_id_test_index', REPO / 'core/project_index.py')


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
    def pack(self, **options): pass
    def grid(self, **options): pass
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
    def insert(self, position, text, **options): self.contents += text
    def see(self, *args): pass
    def winfo_children(self): return []
    def destroy(self): pass


class Tree(Widget):
    def __init__(self, *args, **options):
        super().__init__(*args, **options)
        self.rows, self.selected, self.sequence = {}, [], 0
    def insert(self, parent, position, **options):
        self.sequence += 1
        iid = str(self.sequence)
        self.rows[iid] = dict(options)
        return iid
    def get_children(self): return list(self.rows)
    def selection(self): return tuple(self.selected)
    def selection_set(self, iid):
        if iid not in self.rows: raise AssertionError('unknown injected tree row')
        self.selected = [iid]
    def delete(self, iid):
        self.rows.pop(iid)
        self.selected = [x for x in self.selected if x != iid]
    def item(self, iid, option=None):
        return self.rows[iid][option] if option else self.rows[iid]


class App(Widget):
    def __init__(self, scenario):
        super().__init__()
        self.widgets, self.callbacks, self.protocols = [], [], {}
        self.scenario, self.closed = scenario, False
    def title(self, *args): pass
    def geometry(self, *args): pass
    def minsize(self, *args): pass
    def after(self, delay, callback): self.callbacks.append(callback)
    def protocol(self, event, callback): self.protocols[event] = callback
    def mainloop(self):
        try: self.scenario(self)
        finally: self.protocols['WM_DELETE_WINDOW']()
    def destroy(self): self.closed = True
    def bell(self): pass
    def click(self, label):
        widget = next(w for w in self.widgets if w.options.get('text') == label and 'command' in w.options)
        widget.options['command']()
    def pump(self): self.callbacks.pop(0)()
    def tree(self): return next(w for w in self.widgets if isinstance(w, Tree))
    def selected_text(self):
        tree = self.tree(); return tree.item(tree.selection()[0], 'text')


class Voice:
    """Cooperating turn guard only; never constructs a speech controller."""
    def __init__(self, *args, **options):
        self.closed = self.enabled = self.blocked = self.start_blocked = False
        self.retiring, self.current_turn, self.next_turn = None, None, 0
        self.state, self.voice_label = 'off', 'injected/no speech'
    def begin_turn(self):
        if self.current_turn is not None: return None
        self.next_turn += 1; self.current_turn = self.next_turn; return self.current_turn
    def finish_turn(self, turn, *args):
        if self.current_turn == turn: self.current_turn = None
    def poll_retirement(self): pass
    def start(self): raise AssertionError('speech start excluded')
    def stop(self): pass
    def close(self): self.closed = True


class Chat:
    model_name = 'injected/no model'
    def __init__(self, active=None):
        self.current_project, self.current_project_name = active, None
        self.requests, self.stopped = [], False
        self.research_manager = types.SimpleNamespace(event_callback=None, shutdown=self.shutdown)
    def shutdown(self): self.stopped = True
    def ask(self, text, image_path=None):
        self.requests.append((text, image_path))
        match = re.search(r'\bopen\s+(?:my\s+)?(.+?)(?:\s+project)?$', text, re.I)
        if match:
            found = index.find_project(match.group(1).strip(' .'))
            if found:
                self.current_project = found['path']; self.current_project_name = found['name']
        return 'injected workspace response'


class ImmediateWorker:
    def __init__(self, target, args=(), **options): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class ProjectIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ideaforge-id003-review-')
        self.root = Path(self.temp.name).absolute()
        self.projects_root = self.root / 'projects'
        self.projects_root.mkdir()
        self.old_roots = projects.ROOT, index.ROOT
        projects.ROOT = index.ROOT = self.projects_root
    def tearDown(self):
        projects.ROOT, index.ROOT = self.old_roots
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).absolute())
        self.assertTrue(self.root.name.startswith('ideaforge-id003-review-'))
        self.temp.cleanup()
    def record(self, folder, name, timestamp):
        path = self.projects_root / folder; path.mkdir()
        doc = path / 'project.json'
        doc.write_text(json.dumps({'name': name, 'idea': 'synthetic', 'plan': {}}), encoding='utf-8')
        os.utime(doc, (timestamp, timestamp))
        return path
    def snapshot(self, path):
        return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    def run_ui(self, scenario, active=None):
        app, chat = App(scenario), Chat(active)
        (self.root / 'ai').mkdir(); (self.root / 'ai/config.json').write_text('{}', encoding='utf-8')
        tk = types.ModuleType('tkinter'); ttk = types.ModuleType('tkinter.ttk')
        tk.Tk = lambda: app; tk.Text = tk.Canvas = Widget
        tk.StringVar = tk.BooleanVar = Value
        for name in ('Frame', 'Label', 'Button', 'Checkbutton', 'Panedwindow', 'Scrollbar'): setattr(ttk, name, Widget)
        ttk.Treeview = Tree
        dialog = types.SimpleNamespace(showinfo=lambda *a, **k: None, showerror=lambda *a, **k: None)
        tk.ttk = ttk; tk.messagebox = dialog
        tk.filedialog = types.SimpleNamespace(askopenfilename=lambda **k: None)
        tk.simpledialog = types.SimpleNamespace(askstring=lambda *a, **k: None)
        ai = types.ModuleType('ai'); ai.__path__ = []
        chat_module = types.ModuleType('ai.chat'); chat_module.IdeaForgeChat = Chat
        voice_module = types.ModuleType('ai.hands_free'); voice_module.HandsFreeChat = Voice
        voice_module.voice_prompt = lambda text, config: text
        core = types.ModuleType('core'); core.__path__ = []
        state = types.ModuleType('core.project_state'); state.load = lambda path: {}
        pil = types.ModuleType('PIL'); pil.Image = pil.ImageTk = pil.ImageGrab = None
        modules = {'tkinter': tk, 'tkinter.ttk': ttk, 'ai': ai, 'ai.chat': chat_module,
                   'ai.hands_free': voice_module, 'core': core, 'core.project_index': index,
                   'core.project_state': state, 'PIL': pil}
        previous_cwd = Path.cwd()
        self.chat = chat
        try:
            os.chdir(self.root)
            with patch.dict(sys.modules, modules):
                ui = load_source('_id_test_actual_main', REPO / 'ideaforge.py')
                with patch.object(ui.threading, 'Thread', ImmediateWorker):
                    ui.main(chat_factory=lambda: chat)
        finally:
            os.chdir(previous_cwd); sys.modules.pop('_id_test_actual_main', None)
        self.assertTrue(app.closed); self.assertTrue(chat.stopped)
        return app

    def test_same_titles_have_distinct_numeric_json_and_folders(self):
        with patch.object(projects.secrets, 'randbelow', side_effect=[321, 654]):
            first = projects.create_project('Same title', 'first', {})
            before = self.snapshot(first)
            second = projects.create_project('Same title', 'second', {})
        self.assertEqual(first.name, '10000321'); self.assertEqual(second.name, '10000654')
        self.assertEqual(self.snapshot(first), before)
        for path in (first, second):
            doc = json.loads((path / 'project.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['project_id'], path.name); self.assertEqual(doc['name'], 'Same title')

    def test_collision_file_and_folder_preserved_then_fresh_id(self):
        folder = self.record('10000321', 'keep', 10)
        file = self.projects_root / '10000654'; file.write_bytes(b'keep file')
        before = self.snapshot(folder)
        with patch.object(projects.secrets, 'randbelow', side_effect=[321, 654, 987]):
            created = projects.create_project('New', 'new', {})
        self.assertEqual(created.name, '10000987')
        self.assertEqual(self.snapshot(folder), before); self.assertEqual(file.read_bytes(), b'keep file')

    def test_collision_ceiling_fails_without_overwrite(self):
        keep = self.record('10000321', 'keep', 10); before = self.snapshot(keep)
        with patch.object(projects.secrets, 'randbelow', return_value=321) as rng:
            with self.assertRaises(FileExistsError): projects.create_project('New', 'new', {})
        self.assertEqual(rng.call_count, 100); self.assertEqual(self.snapshot(keep), before)

    def test_concurrent_creators_claim_exclusive_different_folders(self):
        barrier = threading.Barrier(6); counter_lock = threading.Lock()
        local, counter, created, errors = threading.local(), [2000], [], []
        def candidate(_bound):
            if not getattr(local, 'first', False):
                local.first = True; barrier.wait(timeout=4); return 321
            with counter_lock: counter[0] += 1; return counter[0]
        def create():
            try:
                path = projects.create_project('Same title', 'synthetic', {})
                with counter_lock: created.append(path)
            except BaseException as error:
                with counter_lock: errors.append(error)
        workers = [threading.Thread(target=create) for _ in range(6)]
        with patch.object(projects.secrets, 'randbelow', side_effect=candidate):
            for worker in workers: worker.start()
            for worker in workers: worker.join(timeout=8)
        self.assertTrue(all(not x.is_alive() for x in workers)); self.assertEqual(errors, [])
        self.assertEqual(len(created), 6); self.assertEqual(len(set(created)), 6)
        self.assertEqual(sum(path.name == '10000321' for path in created), 1)
        for path in created: self.assertEqual(json.loads((path / 'project.json').read_text())['project_id'], path.name)

    def test_numeric_id_beats_newer_numeric_display_name(self):
        older = self.record('10000321', 'Older actual ID', 10)
        self.record('10000654', '10000321', 20)
        self.assertEqual(index.find_project('10000321')['path'], older)

    def test_unknown_eight_digit_id_has_no_fuzzy_or_title_fallback(self):
        self.record('10000321', '10000999', 20)
        self.assertIsNone(index.find_project('10000999'))
        self.assertIsNone(index.find_project('10000322'))

    def test_legacy_name_lookup_and_bytes_preserved(self):
        legacy = self.record('old-named-project', 'Old Named Project', 10)
        before = self.snapshot(legacy)
        self.assertEqual(index.find_project('old-named-project')['path'], legacy)
        self.assertEqual(index.find_project('Old Named Project')['path'], legacy)
        with patch.object(projects.secrets, 'randbelow', return_value=321): projects.create_project('Old Named Project', 'new', {})
        self.assertEqual(self.snapshot(legacy), before)
        self.assertEqual(index.find_project('old-named-project')['path'], legacy)

    def test_traversal_like_title_is_only_display_metadata(self):
        with patch.object(projects.secrets, 'randbelow', return_value=321):
            root = projects.create_project('../NUL/other', 'synthetic', {})
        self.assertEqual(root.parent, self.projects_root); self.assertEqual(root.name, '10000321')
        self.assertEqual(json.loads((root / 'project.json').read_text())['name'], '../NUL/other')

    def test_actual_ui_opens_older_duplicate_selected_row(self):
        older = self.record('10000321', 'Duplicate', 10); newer = self.record('10000654', 'Duplicate', 20)
        def scenario(app):
            tree = app.tree(); self.assertEqual([r['text'] for r in tree.rows.values()], ['Duplicate', 'Duplicate'])
            tree.selection_set(tree.get_children()[1]); app.click('Open'); app.pump()
            self.assertEqual(self.chat.requests, [('open 10000321 project', None)])
            self.assertEqual(self.chat.current_project, older); self.assertNotEqual(self.chat.current_project, newer)
        self.run_ui(scenario)

    def test_actual_ui_refresh_preserves_selected_path_over_different_active(self):
        selected = self.record('10000321', 'Duplicate', 10); active = self.record('10000654', 'Duplicate', 20)
        def scenario(app):
            tree = app.tree(); tree.selection_set(tree.get_children()[1])
            self.chat.research_manager.event_callback('research_complete', {})
            app.pump(); self.assertEqual(len(tree.selection()), 1)
            self.assertEqual(tree.selection()[0], tree.get_children()[1])
            app.click('Open'); app.pump(); self.assertEqual(self.chat.current_project, selected)
            self.assertEqual(self.chat.requests[0][0], 'open 10000321 project')
        self.run_ui(scenario, active)

    def test_actual_ui_refresh_keeps_selected_path_after_reorder(self):
        selected = self.record('10000321', 'Duplicate', 10); active = self.record('10000654', 'Duplicate', 20)
        def scenario(app):
            tree = app.tree(); tree.selection_set(tree.get_children()[1])
            os.utime(selected / 'project.json', (30, 30))
            self.chat.research_manager.event_callback('research_complete', {})
            app.pump(); self.assertEqual(tree.selection()[0], tree.get_children()[0])
            app.click('Open'); app.pump(); self.assertEqual(self.chat.current_project, selected)
        self.run_ui(scenario, active)

    def test_actual_ui_notification_opens_path_not_duplicate_title(self):
        older = self.record('10000321', 'Duplicate', 10); newer = self.record('10000654', 'Duplicate', 20)
        def scenario(app):
            self.chat.research_manager.event_callback('useful_discovery', {'project': str(older), 'discoveries': []})
            app.pump(); app.click('Open Project'); app.pump()
            self.assertEqual(self.chat.requests[0][0], 'open 10000321 project')
            self.assertEqual(self.chat.current_project, older)
        self.run_ui(scenario, newer)

    def test_actual_ui_numeric_title_selectable_by_row_without_shadowing(self):
        self.record('10000321', 'Actual ID', 10); titled = self.record('10000654', '10000321', 20)
        def scenario(app):
            tree = app.tree(); self.assertEqual(tree.rows[tree.get_children()[0]]['text'], '10000321')
            tree.selection_set(tree.get_children()[0]); app.click('Open'); app.pump()
            self.assertEqual(self.chat.current_project, titled)
            self.assertEqual(self.chat.requests[0][0], 'open 10000654 project')
        self.run_ui(scenario)

    def test_actual_ui_legacy_folder_and_readable_name_retained(self):
        legacy = self.record('legacy-hinge', 'Hinge Prototype', 10)
        before = self.snapshot(legacy)
        def scenario(app):
            tree = app.tree(); self.assertEqual(tree.rows[tree.get_children()[0]]['text'], 'Hinge Prototype')
            tree.selection_set(tree.get_children()[0]); app.click('Open'); app.pump()
            self.assertEqual(self.chat.requests[0][0], 'open legacy-hinge project')
            self.assertEqual(self.chat.current_project, legacy)
        self.run_ui(scenario)
        self.assertEqual(self.snapshot(legacy), before)


if __name__ == '__main__': unittest.main(verbosity=2)
