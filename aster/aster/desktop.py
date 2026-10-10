"""Native Tk control panel for deterministic Aster mechanics, never desktop control.

Tk is imported only by launch(). Importing the CLI/controller does not require a
GUI installation. Browser handoffs require an explicit review and confirmation.
The UI never calls a shell or audio player. An explicitly
configured remote client polls off-thread and passes text to the state owner.
"""
import json
import time
from datetime import datetime

from .dashboard import DashboardWorker, HISTORIES


def launch(state, *, auto_start=False, remote_client=None):
    """Open the local window; Store belongs to its worker, not the CLI caller."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as exc:
        raise RuntimeError('Desktop needs Python with tkinter/Tk. Use the CLI on this installation.') from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError('Desktop could not open a graphical display. Run it in a local graphical session, '
                           'or use the CLI. No background server was started.') from exc
    app = None
    normal_exit = False
    try:
        options = {}
        if auto_start:
            options['auto_start'] = True
        if remote_client is not None:
            options['remote_client'] = remote_client
        app = DesktopWindow(root, state, tk, ttk, messagebox, **options)
        root.mainloop()
        normal_exit = app.exit_code == 0
        return app.exit_code
    finally:
        if app is not None:
            app.worker.close(clean=normal_exit)
            app.worker.wait_closed()
        try:
            root.destroy()
        except tk.TclError:
            pass


def _when(timestamp):
    return datetime.fromtimestamp(timestamp).astimezone().strftime('%b %d %H:%M:%S')


def _formatted(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


class DesktopWindow:
    """Tk-only presentation. All storage work runs through DashboardWorker."""

    def __init__(self, root, state, tk, ttk, messagebox, worker_factory=DashboardWorker, *, auto_start=False, remote_client=None):
        from tkinter import font
        self.root, self.tk, self.ttk, self.dialogs = root, tk, ttk, messagebox
        self.font_family = font.nametofont('TkDefaultFont', root=root).actual('family')
        self.fixed_family = font.nametofont('TkFixedFont', root=root).actual('family')
        root.option_add('*Font', (self.font_family, 10))
        self.exit_code = 0
        self._closing = self._busy = False
        self._snapshot = None
        self._buttons = []
        self._editors = []
        self._history_target = None
        self._saved_prompt = None
        self._file_clean_text = ''
        self._last_queue_click = None
        root.title('Aster · Local workstation')
        width = min(1120, max(640, root.winfo_screenwidth() - 64))
        height = min(820, max(480, root.winfo_screenheight() - 100))
        root.geometry(f'{width}x{height}')
        root.minsize(min(840, width), min(620, height))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.configure(background='#eff3f7')
        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('TFrame', background='#eff3f7')
        style.configure('TLabel', background='#eff3f7', foreground='#182638', font=(self.font_family, 10))
        style.configure('TButton', padding=(12, 7), font=(self.font_family, 10))
        style.configure('Primary.TButton', background='#c4e9df', foreground='#133f35')
        style.configure('TNotebook', background='#eff3f7', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 10))
        style.configure('Treeview', rowheight=27, font=(self.font_family, 10))
        style.configure('Treeview.Heading', font=(self.font_family, 10, 'bold'))
        header = tk.Frame(root, background='#182d45', padx=22, pady=17)
        header.grid(row=0, column=0, sticky='ew')
        tk.Label(header, text='Aster', background='#182d45', foreground='white',
                 font=(self.font_family, 24, 'bold')).pack(side='left')
        tk.Label(header, text='LOCAL WORKSTATION', background='#182d45', foreground='#adc5de',
                 font=(self.font_family, 10)).pack(side='left', padx=20)
        self.identity = tk.StringVar(value='Opening private local state...')
        tk.Label(header, textvariable=self.identity, background='#182d45', foreground='#d1e1f0',
                 font=(self.font_family, 9)).pack(side='right')
        banner = tk.Frame(root, background='#fff0cf', padx=22, pady=11)
        banner.grid(row=1, column=0, sticky='ew')
        tk.Label(banner, text='NewBrain unavailable', background='#fff0cf', foreground='#724b0a',
                 font=(self.font_family, 11, 'bold')).pack(anchor='w')
        tk.Label(banner, text='Requests are saved as pending. No AI answers, fallback model, or automatic actions.',
                 background='#fff0cf', foreground='#724b0a').pack(anchor='w', pady=(3, 0))
        body = ttk.Frame(root, padding=(18, 14))
        body.grid(row=2, column=0, sticky='nsew')
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill='both', expand=True)
        self._requests_tab()
        self._files_tab()
        self._queue_tab()
        self._history_tab()
        self._research_tab()
        self._status_tab()
        self._browser_tab()
        footer = ttk.Frame(root, padding=(20, 8))
        footer.grid(row=3, column=0, sticky='ew')
        self.status = tk.StringVar(value='Opening state...')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, wraplength=850).grid(row=0, column=0, sticky='w')
        self._button(footer, 'Refresh', lambda: self._submit('snapshot')).grid(row=0, column=1, rowspan=2)
        self.memory_status = tk.StringVar(value='Local memory observation pending. External app closure is disabled.')
        ttk.Label(footer, textvariable=self.memory_status, wraplength=850).grid(row=1, column=0, sticky='w')
        options = {}
        if auto_start:
            options['auto_start'] = True
        if remote_client is not None:
            options['remote_client'] = remote_client
        self.worker = worker_factory(state, **options)
        self._set_busy(True)
        root.protocol('WM_DELETE_WINDOW', self._close)
        root.report_callback_exception = self._callback_failed
        root.after(50, self._poll)
        root.after(5000, self._memory_tick)

    def _tab(self, title, description):
        frame = self.ttk.Frame(self.notebook, padding=16)
        self.notebook.add(frame, text=title)
        self.ttk.Label(frame, text=description, wraplength=970).pack(anchor='w', pady=(0, 12))
        return frame

    def _button(self, parent, text, command, primary=False):
        button = self.ttk.Button(parent, text=text, command=command,
                                 style='Primary.TButton' if primary else 'TButton')
        self._buttons.append(button)
        return button

    def _text(self, parent, height=7, editable=False):
        frame = self.ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=(0, 8))
        box = self.tk.Text(frame, height=height, wrap='word', font=(self.fixed_family, 10),
                           padx=10, pady=9, relief='solid', borderwidth=1,
                           background='white', foreground='#182638', undo=editable)
        scroll = self.ttk.Scrollbar(frame, orient='vertical', command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        box.pack(side='left', fill='both', expand=True)
        if editable:
            self._editors.append(box)
        else:
            box.configure(state='disabled')
        return box

    def _entry(self, parent, variable, width=None):
        entry = self.ttk.Entry(parent, textvariable=variable, width=width)
        self._editors.append(entry)
        return entry

    def _tree(self, parent, columns, height=6):
        frame = self.ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=(0, 8))
        tree = self.ttk.Treeview(frame, columns=[key for key, _, _ in columns],
                                show='headings', selectmode='browse', height=height)
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=70, stretch=True)
        y = self.ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        x = self.ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        y.pack(side='right', fill='y')
        x.pack(side='bottom', fill='x')
        tree.pack(fill='both', expand=True)
        return tree

    def _requests_tab(self):
        frame = self._tab('Requests', 'Write a request to keep for later. Saving it does not run tools or produce a response.')
        self.prompt = self._text(frame, height=6, editable=True)
        controls = self.ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 16))
        self._button(controls, 'Save pending request', self._save_request, True).pack(side='left')
        self.pending_count = self.tk.StringVar(value='')
        self.ttk.Label(controls, textvariable=self.pending_count).pack(side='right')
        self.ttk.Label(frame, text='Saved requests · latest 100', font=(self.font_family, 11, 'bold')).pack(anchor='w', pady=(0, 8))
        self.requests = self._tree(frame, [('at', 'Saved (local time)', 160), ('status', 'State', 185),
                                         ('body', 'Your request', 620)], 5)
        self._button(frame, 'View selected request', lambda: self._view('prompts', self.requests, self.request_detail)).pack(anchor='w', pady=(0, 8))
        self.request_detail = self._text(frame, height=5)
        self._replace(self.request_detail, 'Saved requests will appear here. This area contains your requests, not AI responses.')

    def _files_tab(self):
        frame = self._tab('Workspace', 'Text files only, up to 256 KiB. Paths are relative to Aster’s workspace. Program source can be saved; it cannot be executed.')
        self.workspace = self.tk.StringVar(value='')
        self.ttk.Label(frame, textvariable=self.workspace, wraplength=950).pack(anchor='w', pady=(0, 10))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 9))
        self.ttk.Label(row, text='Relative path').pack(side='left', padx=(0, 10))
        self.file_path = self.tk.StringVar(value='notes/example.txt')
        self._entry(row, self.file_path).pack(side='left', fill='x', expand=True)
        self._button(row, 'Read file', self._read_file).pack(side='left', padx=(8, 0))
        self.file_text = self._text(frame, height=19, editable=True)
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=5)
        self._button(row, 'Save file...', lambda: self._submit('prepare_write', path=self.file_path.get(),
                     content=self.file_text.get('1.0', 'end-1c')), True).pack(side='left')
        self._button(row, 'Move to trash...', lambda: self._submit('prepare_trash', path=self.file_path.get())).pack(side='left', padx=8)
        self.ttk.Label(frame, text='Writes and trash require confirmation. Use History > changes to undo an applied change.\nUnsaved editor text is not retained when you close the window.', wraplength=950).pack(anchor='w', pady=(10, 0))

    def _queue_tab(self):
        frame = self._tab('Job queue', 'Only explicit bounded actions are available. Queueing does not execute. Run next once reviews and runs the oldest queued job.')
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 7))
        self.job_action = self.tk.StringVar(value='research.links')
        self.job_picker = self.ttk.Combobox(row, textvariable=self.job_action, state='readonly', width=22,
                                          values=('research.links', 'memory.append', 'file.write'))
        self.job_picker.pack(side='left')
        self.job_picker.bind('<<ComboboxSelected>>', self._job_template)
        self.ttk.Label(row, text='Measured budget (seconds)').pack(side='left', padx=(18, 6))
        self.budget = self.tk.StringVar(value='5')
        self._entry(row, self.budget, 7).pack(side='left')
        self.ttk.Label(frame, text='Arguments (JSON); text below is data only').pack(anchor='w', pady=(0, 4))
        self.job_args = self._text(frame, height=3, editable=True)
        self._job_template()
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 12))
        self._button(row, 'Add to queue', self._queue, True).pack(side='left')
        self._button(row, 'Run next once...', lambda: self._submit('prepare_run')).pack(side='left', padx=8)
        self.queue_count = self.tk.StringVar(value='')
        self.ttk.Label(row, textvariable=self.queue_count).pack(side='right')
        self.jobs = self._tree(frame, [('at', 'Queued (local time)', 160), ('action', 'Action', 180),
                                     ('status', 'State', 160), ('id', 'Job ID', 350)], 3)
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 8))
        for label, command in [('Pause selected', 'pause'), ('Resume selected', 'resume'), ('Cancel selected', 'cancel')]:
            self._button(row, label, lambda c=command: self._control(c)).pack(side='left', padx=(0, 8))
        self._button(row, 'View selected', lambda: self._view('jobs', self.jobs, self.job_detail)).pack(side='right')
        self.ttk.Label(frame, text='Pause/cancel applies before execution only. Active writes finish atomically. A time budget is measured, not an enforced timeout.', wraplength=970).pack(anchor='w', pady=(0, 8))
        self.job_detail = self._text(frame, height=5)

    def _history_tab(self):
        frame = self._tab('History', 'Durable local history stays with Aster’s identity. Lists show the latest 100 entries; saved history is not pruned.')
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 10))
        self.history_kind = self.tk.StringVar(value='changes')
        picker = self.ttk.Combobox(row, textvariable=self.history_kind, values=HISTORIES, state='readonly', width=20)
        picker.pack(side='left')
        picker.bind('<<ComboboxSelected>>', lambda event: self._render_history())
        self._button(row, 'View selected', lambda: self._view(self.history_kind.get(), self.history, self.history_detail)).pack(side='left', padx=8)
        self._button(row, 'Undo selected change...', self._undo).pack(side='left')
        self._button(row, 'Reconcile interrupted...', lambda: self._submit('prepare_recover')).pack(side='right')
        self.history = self._tree(frame, [('at', 'Time (local)', 150), ('type', 'Kind / state', 220),
                                         ('preview', 'Summary', 580)], 5)
        self.history_detail = self._text(frame, height=10)

    def _research_tab(self):
        frame = self._tab('Research exports',
            'Owner-selected workspace exports only. This is not a live app connection. '
            'Research records are untrusted data with owner-declared provenance.')
        self._manifest_choices = {}
        self._research_state = None
        self.research_selection = self.tk.StringVar(value='No export status loaded. Refresh to inspect this state.')
        self.ttk.Label(frame, textvariable=self.research_selection, wraplength=960).pack(anchor='w', pady=(0, 10))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 9))
        self.ttk.Label(row, text='Manifest file').pack(side='left', padx=(0, 8))
        self.manifest_path = self.tk.StringVar(value='integrations/manifest.json')
        self._entry(row, self.manifest_path).pack(side='left', fill='x', expand=True)
        self._button(row, 'Review & register...', lambda: self._submit('prepare_register',
                     path=self.manifest_path.get())).pack(side='left', padx=(8, 0))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 9))
        self.ttk.Label(row, text='Registered capability').pack(side='left', padx=(0, 8))
        self.manifest_choice = self.tk.StringVar()
        self.manifest_picker = self.ttk.Combobox(row, textvariable=self.manifest_choice,
                                               state='readonly', width=48)
        self.manifest_picker.pack(side='left', fill='x', expand=True)
        self.manifest_picker.bind('<<ComboboxSelected>>', lambda event: self._research_projects())
        self.ttk.Label(row, text='Project').pack(side='left', padx=8)
        self.project_choice = self.tk.StringVar()
        self.project_picker = self.ttk.Combobox(row, textvariable=self.project_choice,
                                              state='readonly', width=23)
        self.project_picker.pack(side='left')
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 10))
        self.ttk.Label(row, text='Export file').pack(side='left', padx=(0, 8))
        self.export_path = self.tk.StringVar(value='integrations/export.json')
        self._entry(row, self.export_path).pack(side='left', fill='x', expand=True)
        self._button(row, 'Review & select...', self._select_export, True).pack(side='left', padx=(8, 0))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 9))
        self._button(row, 'Refresh exports', lambda: self._submit('research_status')).pack(side='left')
        self._button(row, 'Inspect selected', lambda: self._submit('research_inspect')).pack(side='left', padx=5)
        self._button(row, 'Read selected', lambda: self._submit('research_read')).pack(side='left', padx=5)
        self._button(row, 'Clear selection...', lambda: self._submit('prepare_clear')).pack(side='left', padx=5)
        self._button(row, 'Disable capability...', self._disable_export).pack(side='left', padx=5)
        self.ttk.Label(frame, text='Paths must already exist inside Aster’s workspace. Registration and selection '
            'are bound to the exact SHA-256 reviewed. No external app permissions are granted.',
            wraplength=960).pack(anchor='w', pady=(0, 10))
        self.research_detail = self._text(frame, height=13)

    def _research_projects(self):
        manifest = self._manifest_choices.get(self.manifest_choice.get())
        ids = [p['id'] for p in manifest['manifest']['projects']] if manifest else []
        self.project_picker.configure(values=ids)
        if self.project_choice.get() not in ids:
            self.project_choice.set(ids[0] if ids else '')

    def _select_export(self):
        manifest = self._manifest_choices.get(self.manifest_choice.get())
        if manifest is None:
            self.status.set('Register or choose an enabled export capability first.')
            return
        self._submit('prepare_select', manifest_id=manifest['id'],
                     project_id=self.project_choice.get(), path=self.export_path.get())

    def _disable_export(self):
        manifest = self._manifest_choices.get(self.manifest_choice.get())
        if manifest is None:
            self.status.set('Choose the registered capability to disable.')
            return
        self._submit('prepare_disable', manifest_id=manifest['id'])

    def _render_research(self, state):
        self._research_state = state
        self._manifest_choices = {
            item['manifest']['app_id'] + ' · ' + item['id']: item
            for item in state['manifests']
            if item['status'] == 'registered_owner_selected_export_only'}
        names = list(self._manifest_choices)
        self.manifest_picker.configure(values=names)
        if self.manifest_choice.get() not in names:
            self.manifest_choice.set(names[0] if names else '')
        self._research_projects()
        selection = state['selection']
        if selection:
            self.research_selection.set('Current export: ' + selection.get('app_id', 'disabled') +
                ' / ' + selection['project_id'] + ' · ' + selection['status'])
        else:
            self.research_selection.set('No selected export. Live app commands are unavailable.')

    def _confirm_dialog(self, title, message):
        # Long manifests/project lists remain reviewable without overflowing the
        # screen. The default focus and Escape are cancel, never approval.
        dialog = self.tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.geometry('760x560')
        dialog.minsize(560, 380)
        approved = [False]
        frame = self.ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        self.ttk.Label(frame, text=title, font=(self.font_family, 14, 'bold')).pack(anchor='w', pady=(0, 12))
        details = self._text(frame, height=15)
        self._replace(details, message)
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(8, 0))
        def decide(value):
            approved[0] = value
            dialog.destroy()
        cancel = self.ttk.Button(row, text='Cancel', command=lambda: decide(False))
        cancel.pack(side='right')
        self.ttk.Button(row, text='Confirm action', command=lambda: decide(True),
                        style='Primary.TButton').pack(side='right', padx=10)
        dialog.protocol('WM_DELETE_WINDOW', lambda: decide(False))
        dialog.bind('<Escape>', lambda event: decide(False))
        dialog.grab_set()
        cancel.focus_set()
        self.root.wait_window(dialog)
        return approved[0]

    def _status_tab(self):
        frame = self._tab('Voice & status', 'Inspect supplied local assets and optional app registrations. Registration does not grant research access or command permission.')
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 12))
        self._button(row, 'Inspect voice audition', lambda: self._submit('voice'), True).pack(side='left')
        self._button(row, 'Check app registrations', lambda: self._submit('apps')).pack(side='left', padx=8)
        self._button(row, 'Memory & recovery', lambda: self._submit('system_status')).pack(side='left')
        self.ttk.Label(frame, text='Voice preview is a prerecorded audition, not an AI answer. If verified, copy the local preview path and open it manually. Voice inspection never starts a player or browser. Live speech is unavailable.', wraplength=970).pack(anchor='w', pady=(0, 12))
        from .support import OPERATIONS
        tools = self.ttk.LabelFrame(frame, text='Local support modules · explicit actions only', padding=8)
        tools.pack(fill='x', pady=(0, 8))
        selectors = self.ttk.Frame(tools)
        selectors.pack(fill='x')
        self.support_module = self.tk.StringVar(value='memory')
        self.support_operation = self.tk.StringVar(value='status')
        self.support_module_picker = self.ttk.Combobox(selectors, textvariable=self.support_module,
            values=list(OPERATIONS), state='readonly', width=18)
        self.support_module_picker.pack(side='left')
        self.support_operation_picker = self.ttk.Combobox(selectors, textvariable=self.support_operation,
            values=list(OPERATIONS['memory']), state='readonly', width=20)
        self.support_operation_picker.pack(side='left', padx=8)
        self._button(selectors, 'Review / run local action', self._support_submit).pack(side='left')
        self.support_module_picker.bind('<<ComboboxSelected>>', self._support_choose_module)
        self.support_operation_picker.bind('<<ComboboxSelected>>', self._support_choose_operation)
        self.ttk.Label(tools, text='Edit the example JSON arguments. Mutations require a separate confirmation. '
            'Export imports and trim writes also require the exact preview hash.', wraplength=940).pack(anchor='w')
        self.support_args = self._text(tools, height=4, editable=True)
        self._replace(self.support_args, '{}')
        self.local_status = self._text(frame, height=8)
        self._replace(self.local_status, 'Choose an inspection above.\n\nOpening this window starts no model, network listener, browser, shell, app command, or background job runner. Browser handoffs require the separate Browser controls.')

    def _browser_tab(self):
        frame = self._tab('Browser', 'Read an anonymous static public source here, or separately review a default-browser handoff.')
        self.ttk.Label(frame, text='Public reads use no cookies, accounts, scripts or forms. Page text is untrusted. '
            'Only Read or Follow requests a source. Browser handoffs may use your existing cookies.',
            wraplength=970).pack(anchor='w', pady=(0, 6))
        self.browser_value = self.tk.StringVar(value='')
        self._public_source = None
        self._public_ui_generation = 0
        self._public_pending_generation = None
        self._last_public_click = None
        self.ttk.Label(frame, text='Exact public HTTP(S) URL, or search words for the separate browser handoff').pack(anchor='w')
        self._entry(frame, self.browser_value).pack(fill='x', pady=(0, 6))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 6))
        for kind, label in [('url', 'Review website...'), ('source', 'Review source URL...'), ('search', 'Review Google search...')]:
            self._button(row, label, lambda mode=kind: self._submit('prepare_browser',
                kind=mode, value=self.browser_value.get())).pack(side='left', padx=(0, 6))
        row = self.ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 6))
        self.public_read_button = self._button(row, 'Read public source', self._read_public, primary=True)
        self.public_read_button.pack(side='left', padx=(0, 6))
        self.public_follow_button = self._button(row, 'Follow selected link', self._follow_public)
        self.public_follow_button.pack(side='left', padx=(0, 6))
        # Cancellation is intentionally available while the owning worker waits
        # for a read. It can only invalidate memory and stop that fixed child.
        self.public_cancel_button = self.ttk.Button(row, text='Cancel / clear source', command=self._cancel_public)
        self.public_cancel_button.pack(side='left')
        self.public_link = self.tk.StringVar(value='')
        self.public_link_picker = self.ttk.Combobox(frame, textvariable=self.public_link,
                                                   values=(), state='readonly')
        self.public_link_picker.pack(fill='x', pady=(0, 6))
        self.public_link_picker.bind('<<ComboboxSelected>>', self._public_select_link)
        self.browser_result = self._text(frame, height=10)
        self._replace(self.browser_result, 'No public source has been read and no browser has been opened. '
            'Enter an exact public URL and choose Read public source. Sources and link IDs stay in memory only.')
        self.browser_value.trace_add('write', self._public_url_changed)

    def _clear_public_display(self, message):
        self._public_source = None
        self._public_display = ''
        self.public_link.set('')
        self.public_link_picker.configure(values=())
        self._replace(self.browser_result, message)

    def _public_url_changed(self, *unused):
        self._public_ui_generation += 1
        if hasattr(self, 'worker'):
            self.worker.cancel_public()
        self._clear_public_display('URL changed. Choose Read public source for this exact URL.')

    def _cancel_public(self):
        if self._closing:
            return
        self._public_ui_generation += 1
        self.worker.cancel_public()
        self._clear_public_display('Public source cleared. Any active public read is cancelled; no link remains selected.')
        self.status.set('Public source cleared. No request will be retried.')

    def _read_public(self):
        if self._busy or self._closing:
            return
        value, now = self.browser_value.get(), time.monotonic()
        if self._last_public_click and self._last_public_click[0] == value and now - self._last_public_click[1] < .75:
            self.status.set('This public read was already requested. Read again deliberately to refresh.')
            return
        self._public_ui_generation += 1
        self._clear_public_display('Reading this explicit public URL...')
        if self._submit('public_read', url=value):
            self._last_public_click = (value, now)
            self._public_pending_generation = self._public_ui_generation
            self.status.set('Reading one public source. Cancel / clear source stops this read.')

    def _public_select_link(self, event=None):
        selected = self.public_link_picker.current()
        if self._public_source is not None and 0 <= selected < len(self._public_source['links']):
            link = self._public_source['links'][selected]
            self._replace(self.browser_result, self._public_display +
                          '\n\nSELECTED DESTINATION (no request yet):\n' + link['url'])
            self.browser_result.see('end')

    def _follow_public(self):
        if self._busy or self._closing:
            return
        source = self._public_source
        selected = self.public_link_picker.current()
        if source is None or selected < 0 or selected >= len(source['links']):
            self._cancel_public()
            self.status.set('Choose a link from a current public source before following it.')
            return
        source_id = source['source_id']
        link_id = source['links'][selected]['link_id']
        self._public_ui_generation += 1
        self._clear_public_display('Reading the explicitly selected source link...')
        if self._submit('public_follow', source_id=source_id, link_id=link_id):
            self._public_pending_generation = self._public_ui_generation
            self.status.set('Reading one selected public link. No other link will be followed.')

    def _render_public(self, result):
        if self._public_pending_generation != self._public_ui_generation:
            return  # Source changed or cancelled while the result was pending.
        self._clear_public_display('Public reader: ' + result.get('reason', result.get('status', 'unknown')))
        if result.get('status') not in {'read', 'redirect'}:
            self.status.set('Public reader: ' + result.get('reason', 'failed') + '. No automatic retry.')
            return
        self._public_source = result
        self.public_link_picker.configure(values=tuple(
            str(link['number']) + '. ' + (link['text'] or '(unlabelled)') + ' | ' + link['url']
            for link in result['links']))
        text = ('UNTRUSTED PUBLIC SOURCE\n' + (result['title'] or '(No title)') +
            '\nSource: ' + result['source_url'] + '\nFetched: ' + result['fetched_at'] +
            '\nHTTP: ' + str(result['http_status']) + ' | TLS verified: ' + str(result['tls_verified']) +
            '\nBody SHA-256: ' + (result['body_sha256'] or '(no body read)') +
            '\nTruncation: ' + json.dumps(result['truncated'], sort_keys=True) + '\n\n' + result['text'])
        if result['status'] == 'redirect':
            text += '\nRedirect was not followed. Review and select its destination above, then choose Follow selected link.'
        self._public_display = text
        self._replace(self.browser_result, text)
        self.status.set('Public ' + result['status'] + ': ' + result['reason'] + '. Source claims are not verified.')

    def _support_choose_module(self, event=None):
        from .support import OPERATIONS
        module = self.support_module.get()
        self.support_operation_picker.configure(values=list(OPERATIONS[module]))
        self.support_operation.set('status')
        self._support_choose_operation()

    def _support_choose_operation(self, event=None):
        from .support import operation
        _, _, example = operation(self.support_module.get(), self.support_operation.get())
        self._replace(self.support_args, _formatted(example))

    def _support_submit(self):
        from .support import operation
        module, op = self.support_module.get(), self.support_operation.get()
        _, mutation, _ = operation(module, op)
        self._submit('prepare_support' if mutation else 'support', module=module,
            operation=op, args_json=self.support_args.get('1.0', 'end-1c'))

    def _replace(self, widget, content):
        old = str(widget.cget('state'))
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', content)
        widget.configure(state=old)

    def _set_busy(self, busy):
        self._busy = busy
        state = 'disabled' if busy else 'normal'
        for button in self._buttons:
            button.configure(state=state)
        for editor in self._editors:
            editor.configure(state=state)
        self.job_picker.configure(state='disabled' if busy else 'readonly')
        self.manifest_picker.configure(state='disabled' if busy else 'readonly')
        self.project_picker.configure(state='disabled' if busy else 'readonly')
        for name in ('support_module_picker', 'support_operation_picker', 'public_link_picker'):
            picker = getattr(self, name, None)
            if picker is not None:
                picker.configure(state='disabled' if busy else 'readonly')

    def _submit(self, action, **args):
        if self._busy or self._closing:
            return False
        if action == 'prepare_browser':
            self._public_ui_generation += 1
            self.worker.cancel_public()
            self._clear_public_display('Reviewing a separate default-browser handoff...')
        # A very fast local completion can re-enable the button between the
        # two physical clicks of a double-click. Suppress that exact queue
        # replay while still allowing a deliberate later identical job.
        queue_key = json.dumps(args, sort_keys=True, ensure_ascii=False) if action == 'queue' else None
        now = time.monotonic()
        if queue_key is not None and self._last_queue_click is not None:
            previous_key, previous_time = self._last_queue_click
            if queue_key == previous_key and now - previous_time < 0.75:
                self.status.set('Already added to the queue. Review the saved job below.')
                return False
        if not self.worker.submit(action, **args):
            return False
        if queue_key is not None:
            self._last_queue_click = (queue_key, now)
        self._set_busy(True)
        self.status.set('Working locally...')
        return True

    def _memory_tick(self):
        # Passive sampling never disables editors or launches queued work. If an
        # explicit action is pending, try again at the next bounded interval.
        if self._closing:
            return
        if not self._busy and self.worker.submit('memory_refresh'):
            self._busy = True
        self.root.after(5000, self._memory_tick)

    def _callback_failed(self, exception_type, exception, traceback):
        self.exit_code = 2
        self._closing = True
        self.worker.close(clean=False)
        try:
            self.dialogs.showerror('Aster interface stopped',
                'The interface encountered an error. Saved work is retained; '
                'open Aster manually to inspect recovery. ' + str(exception), parent=self.root)
        finally:
            self.root.after(50, self._poll)

    def _read_file(self):
        if self._busy or self._closing:
            return
        if self.file_text.get('1.0', 'end-1c') != self._file_clean_text:
            if not self.dialogs.askyesno('Replace unsaved editor text',
                'Reading a file will replace the unsaved text in this editor. Continue?',
                default='no', parent=self.root):
                return
        self._submit('read', path=self.file_path.get())

    def _save_request(self):
        prompt = self.prompt.get('1.0', 'end-1c')
        if self._submit('save_request', prompt=prompt):
            self._saved_prompt = prompt

    def _job_template(self, event=None):
        if getattr(self, '_busy', False):
            return
        examples = {'research.links': {'query': 'robot gripper compliant mechanism'},
                    'memory.append': {'text': 'This project uses metric units', 'source': 'user'},
                    'file.write': {'path': 'notes/example.txt', 'text': 'A local note'}}
        self._replace(self.job_args, _formatted(examples[self.job_action.get()]))

    def _queue(self):
        try:
            args = json.loads(self.job_args.get('1.0', 'end-1c'))
            budget = float(self.budget.get())
        except (ValueError, TypeError) as exc:
            self.dialogs.showerror('Check job input', str(exc), parent=self.root)
            return
        self._submit('queue', job_action=self.job_action.get(), job_args=args, budget=budget)

    def _selected(self, tree):
        selected = tree.selection()
        if not selected:
            self.status.set('Select an item first.')
            return None
        return selected[0]

    def _control(self, command):
        item_id = self._selected(self.jobs)
        if item_id:
            self._submit('control', job_id=item_id, command=command)

    def _undo(self):
        if self.history_kind.get() != 'changes':
            self.status.set('Choose the changes history to undo an applied file change.')
            return
        item_id = self._selected(self.history)
        if item_id:
            self._submit('prepare_undo', change_id=item_id)

    def _view(self, kind, tree, target):
        item_id = self._selected(tree)
        if item_id and self._submit('history', kind=kind, item_id=item_id):
            self._history_target = target

    def _fill_tree(self, tree, rows):
        selected = tree.selection()
        children = tree.get_children()
        if children:
            tree.delete(*children)
        for item_id, values in rows:
            tree.insert('', 'end', iid=str(item_id), values=values)
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])

    def _render(self, snapshot):
        self._snapshot = snapshot
        identity = snapshot['identity']
        self.identity.set(f'{identity["name"]} · {identity["id"][:12]}')
        self.workspace.set('Workspace: ' + snapshot['workspace'])
        self.pending_count.set(f'{snapshot["pending_requests"]} pending · no AI responses')
        counts = snapshot['job_counts']
        self.queue_count.set(f'{counts.get("queued", 0)} queued · {counts.get("paused", 0)} paused')
        self._fill_tree(self.requests, [(r['id'], (_when(r['at']), r['status'], r['preview'].replace('\n', ' ')))
                                       for r in snapshot['histories']['prompts']])
        self._fill_tree(self.jobs, [(r['id'], (_when(r['at']), r['action'], r['status'], r['id']))
                                   for r in snapshot['histories']['jobs']])
        self._render_history()
        memory = snapshot.get('memory', {})
        state = memory.get('state', 'unknown')
        admission = 'new jobs allowed' if memory.get('allow_new_jobs') else 'new jobs deferred'
        recovery = ' Recovery review required.' if snapshot.get('lifecycle', {}).get('recovery_required') else ''
        remote = snapshot.get('remote', {})
        remote_note = (' Remote text: ' + remote.get('state', 'starting') + '.'
                       if remote.get('enabled') else ' Remote polling off.')
        self.memory_status.set(f'Local RAM: {state}; {admission}. External app closure disabled.' + recovery + remote_note)

    def _render_history(self):
        if not self._snapshot:
            return
        kind = self.history_kind.get()
        if kind != getattr(self, '_rendered_history_kind', None):
            self._replace(self.history_detail, '')
        self._rendered_history_kind = kind
        rows = self._snapshot['histories'][kind]
        self._fill_tree(self.history, [(r['id'], (_when(r['at']),
            ' · '.join(str(r[key]) for key in ('kind', 'action', 'status') if key in r),
            r.get('path', r.get('preview', r.get('source', str(r['id'])))).replace('\n', ' '))) for r in rows])
        if not self.history.selection():
            self._replace(self.history_detail, '')

    def _poll(self):
        completion = self.worker.poll()
        if completion:
            if completion.action == 'closed':
                self.root.destroy()
                return
            if completion.snapshot:
                self._render(completion.snapshot)
            if completion.error:
                if completion.action.startswith('public_'):
                    self._clear_public_display('Public reader operation failed. No source or link remains selected.')
                if completion.action == 'queue':
                    self._last_queue_click = None
                self.status.set(completion.error)
                if not self._closing:
                    self.dialogs.showerror('Aster could not complete this action', completion.error, parent=self.root)
                if completion.action in {'startup', 'close'}:
                    self.exit_code = 2
                    self._closing = True
                    self.worker.close(clean=False)
            elif not self._closing:
                self._handle_result(completion)
            if not self._closing and not (isinstance(completion.result, dict) and completion.result.get('confirmation_required')):
                self._set_busy(False)
        self.root.after(50, self._poll)

    def _handle_result(self, completion):
        result = completion.result
        if isinstance(result, dict) and result.get('confirmation_required'):
            approved = self._confirm_dialog(result['title'], result['message'])
            # Modal dialog keeps the UI single-flight. The controller retains the
            # exact reviewed bytes until this explicit one-use decision arrives.
            self.worker.submit('confirm' if approved else 'dismiss', ticket=result['ticket'])
            self.status.set('Applying confirmed action...' if approved else 'Dismissing...')
            return
        if isinstance(result, dict) and result.get('surface') == 'research':
            self._render_research(result['state'])
            self._replace(self.research_detail, _formatted(result['result']))
            self.status.set('Local export operation complete. Provenance is owner-declared; no live app was accessed.')
        elif isinstance(result, dict) and result.get('surface') == 'public_reader':
            self._render_public(result['result'])
        elif isinstance(result, dict) and result.get('surface') == 'browser':
            self._replace(self.browser_result, _formatted(result['result']))
            self.status.set(result['result']['message'])
        elif isinstance(result, dict) and result.get('surface') == 'support':
            if result['module'] == 'memory' and result['operation'] in {'hide', 'delete'}:
                # Selection may differ from the row whose details were last
                # displayed; never infer displayed-content identity from it.
                self._replace(self.history_detail, '')
            self._replace(self.local_status, _formatted(result['result']))
            self.status.set('Local ' + result['module'] + ' / ' + result['operation'] + ' complete.')
        elif completion.action == 'ready':
            self.status.set('Ready. State is locked by this window; close it before using the CLI on the same state.')
            if (completion.snapshot['interrupted_changes'] or completion.snapshot['running_jobs']
                    or completion.snapshot.get('lifecycle', {}).get('recovery_required')):
                self.status.set('Interrupted work needs review. Use History > Reconcile interrupted. No jobs were replayed.')
        elif completion.action == 'snapshot':
            self.status.set('Local state refreshed.')
        elif completion.action == 'memory_refresh':
            pass  # Keep the last explicit action's feedback visible.
        elif completion.action == 'save_request':
            if self.prompt.get('1.0', 'end-1c') == self._saved_prompt:
                self._replace(self.prompt, '')
            self._replace(self.request_detail, _formatted(result))
            self.status.set('Request saved as waiting_for_newbrain. No AI answer was generated.')
        elif completion.action == 'read':
            self._replace(self.file_text, result['text'])
            self._file_clean_text = result['text']
            self.status.set('Read workspace file ' + result['path'])
        elif completion.action == 'history':
            if self._history_target is not None:
                self._replace(self._history_target, _formatted(result))
            self.status.set('Showing saved local history.')
        elif completion.action in {'voice', 'apps', 'system_status'}:
            self._replace(self.local_status, _formatted(result))
            self.status.set('Local inspection complete. No playback, app execution, or network request.')
        elif result is not None:
            if isinstance(result, dict) and result.get('status') == 'written':
                self._file_clean_text = self.file_text.get('1.0', 'end-1c')
            self._replace(self.job_detail, _formatted(result))
            self._replace(self.history_detail, _formatted(result))
            self.status.set(result.get('message', 'Local result: ' + result.get('status', 'recorded'))
                            if isinstance(result, dict) else 'Local operation complete.')

    def _close(self):
        if self._closing:
            return
        if not self.dialogs.askyesno('Close Aster',
            'Close this window? Saved state is retained; unsaved editor text is not. '
            'Any active local operation will finish before state is released.', default='no', parent=self.root):
            return
        self._closing = True
        self._set_busy(True)
        self._public_ui_generation += 1
        self._clear_public_display('Public reader closed.')
        self.public_cancel_button.configure(state='disabled')
        self.status.set('Closing after the current local operation finishes...')
        self.worker.close()
