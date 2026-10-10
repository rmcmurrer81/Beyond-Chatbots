"""Tk wireframe projection with real model transforms; deliberately not a CAD kernel."""
from __future__ import annotations
import copy
import json
import math
import os
import tempfile
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from .model import bounds, demo, digest, geometry, load, rotate, validate, world_vertices
from .checks import run_checks
from .store import Store, compare
from .jobs import queue_refresh, run_one


def save_input(root, scene):
    scene = validate(scene)
    folder = Path(root)/'workspace3d'; folder.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='assembly-',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle:
            json.dump(scene,handle,indent=2,allow_nan=False); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,folder/'assembly.json')
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class Workspace(ttk.Frame):
    def __init__(self, master, root=None, **kwargs):
        super().__init__(master,**kwargs)
        self.results = queue.Queue(); self.busy = False
        self.project = None; self.store = None; self.revision = None
        self.scene = {'schema_version':1,'units':'mm','parts':[],'unknowns':[]}
        self.demo_mode = False; self.selected = None; self.yaw = -35; self.pitch = 25
        self.zoom = 1.; self.pan = [0.,0.]; self.last_drag = None
        self.exploded = tk.BooleanVar(value=False)
        self.preview = tk.BooleanVar(value=False); self.phase = 0
        self.history_ids = []; self.destroyed = False
        toolbar = ttk.Frame(self); toolbar.pack(fill='x')
        for label,command in [('Import assembly',self.import_scene),('Add part',self.add_part),('Edit scene',self.edit_scene),('Requirements',self.edit_requirements),('Printer profile',self.edit_printer),
                              ('Demo',self.show_demo),('Latest',self.show_latest),('Fit',self.fit),('Run checks',self.test_scene)]:
            ttk.Button(toolbar,text=label,command=command).pack(side='left',padx=2)
        toolbar2 = ttk.Frame(self); toolbar2.pack(fill='x')
        ttk.Checkbutton(toolbar2,text='Exploded view',variable=self.exploded,command=self.draw).pack(side='left')
        ttk.Checkbutton(toolbar2,text='Kinematic preview (not physics)',variable=self.preview).pack(side='left')
        ttk.Button(toolbar2,text='Accept workspace baseline',command=self.accept).pack(side='left',padx=6)
        self.status = ttk.Label(self,text='Open a project to load its assembly.'); self.status.pack(fill='x')
        pane = ttk.Panedwindow(self,orient='horizontal'); pane.pack(fill='both',expand=True)
        left = ttk.Frame(pane); pane.add(left,weight=1)
        ttk.Label(left,text='Parts / local millimetres').pack(anchor='w')
        self.parts = tk.Listbox(left,width=22,exportselection=False); self.parts.pack(fill='both',expand=True)
        self.parts.bind('<<ListboxSelect>>',self.select_part)
        self.canvas = tk.Canvas(pane,background='#071b2c',highlightthickness=0,width=600,height=350)
        pane.add(self.canvas,weight=4)
        right = ttk.Frame(pane); pane.add(right,weight=2)
        self.details = tk.Text(right,width=38,height=16,wrap='word',state='disabled',background='#102b40',foreground='#bfeaff')
        self.details.pack(fill='both',expand=True)
        self.history = ttk.Combobox(right,state='readonly'); self.history.pack(fill='x')
        ttk.Button(right,text='Preview selected revision',command=self.show_history).pack(fill='x')
        ttk.Button(right,text='Restore selected as new candidate',command=self.restore).pack(fill='x')
        ttk.Label(self,text='Drag: orbit · Shift-drag: pan · Wheel: zoom · Click: select. Wireframe / geometric screening only.').pack(fill='x')
        self.canvas.bind('<Configure>',lambda event:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.drag_start)
        self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<MouseWheel>',lambda event:self.wheel(1 if event.delta>0 else -1))
        self.canvas.bind('<Button-4>',lambda event:self.wheel(1))
        self.canvas.bind('<Button-5>',lambda event:self.wheel(-1))
        self.bind('<Destroy>',self.on_destroy)
        self.timer = self.after(150,self.tick)
        if root is not None: self.set_project(root)

    def on_destroy(self,event):
        if event.widget is self:
            self.destroyed = True
            if self.timer:
                try: self.after_cancel(self.timer)
                except tk.TclError: pass

    def set_project(self, root):
        path = Path(root).resolve() if root else None
        if path == self.project: return
        self.project = path; self.store = Store(path) if path else None
        self.revision = None; self.demo_mode = False; self.selected = None
        if self.store:
            # Queue only. The app worker executes checks off the Tk thread.
            try: queue_refresh(path)
            except Exception as error: self.set_details(str(error))
        self.show_latest()

    def set_details(self,text):
        self.details.configure(state='normal'); self.details.delete('1.0','end')
        self.details.insert('end',text); self.details.configure(state='disabled')

    def install(self,scene,revision=None):
        self.scene = validate(scene); self.revision = revision
        self.parts.delete(0,'end')
        for part in scene['parts']: self.parts.insert('end',part['id'])
        self.selected = None; self.fit(); self.describe()

    def show_latest(self):
        self.demo_mode = False
        revision = self.store.revision() if self.store else None
        scene = revision['scene'] if revision else {'schema_version':1,'units':'mm','parts':[],
                'unknowns':['No geometry yet. Add measured parts or import an assembly JSON. Research cannot supply missing dimensions by itself.']}
        self.install(scene,revision)
        self.refresh_history()

    def show_demo(self):
        self.demo_mode = True; self.install(demo())

    def refresh_history(self):
        rows = self.store.history() if self.store else []
        self.history_ids = [r['id'] for r in rows]
        self.history['values'] = [f"{r['id'][:8]} · {r['reason'][:38]}" for r in rows]
        if rows: self.history.current(0)

    def selected_revision(self):
        index = self.history.current()
        return self.store.revision(self.history_ids[index]) if self.store and 0<=index<len(self.history_ids) else None

    def show_history(self):
        revision = self.selected_revision()
        if revision: self.demo_mode=False; self.install(revision['scene'],revision)

    def describe(self, tests=None):
        title = self.scene.get('title','Assembly')
        prefix = 'EXAMPLE ONLY' if self.demo_mode else 'CANDIDATE'
        if self.revision and self.store and self.store.pointer('accepted') == self.revision['id']: prefix = 'WORKSPACE BASELINE'
        self.status.configure(text=f'{prefix} · {title} · {len(self.scene["parts"])} part(s) · mm · physics not validated')
        lines = [self.scene.get('title','Assembly'),'','Unknowns:']+self.scene.get('unknowns',[])
        if self.scene.get('requirements'):
            lines += ['', 'Requirement map (not validated):',json.dumps(self.scene['requirements'],indent=2)]
        if self.revision:
            lines += ['', 'Why this revision:',self.revision['reason']]
            before = self.store.revision(self.revision['parent']) if self.revision.get('parent') else None
            lines += ['Changes: '+json.dumps(compare(before['scene'] if before else None,self.scene)),
                      'Sources: '+json.dumps(self.revision['sources'],indent=2)]
            tests = tests or self.revision['tests']
        if self.selected:
            part = next((p for p in self.scene['parts'] if p['id']==self.selected),None)
            lines += ['','Selected part:',json.dumps(part,indent=2)]
        if tests:
            from fabrication.printer_fit import scene_receipts, stale_receipts, same_json
            current_fit=scene_receipts(self.scene,self.project if self.project and (self.project/'project.json').exists() else None)
            for row in current_fit: row['axis_aligned_fit']=None
            if not same_json(tests.get('printer_fit'),current_fit):
                tests=copy.deepcopy(tests)
                tests['printer_fit']=stale_receipts(self.scene)
            lines += ['', 'Geometric screening:',f"Status: {tests['status']}",
                      'Possible bounding-box overlaps: '+json.dumps(tests['possible_aabb_overlaps']),
                      'Printer fit: '+json.dumps(tests['printer_fit']),
                      f"Joint sweeps: {len(tests['joint_sweeps'])} (9 positions each)"]+tests['limitations']
        if self.store:
            errors = [r['error'] for r in self.store.job_status() if r['error']]
            if errors: lines += ['', 'Recent job warnings:']+errors
        self.set_details('\n'.join(lines))

    def fit(self):
        self.zoom=1.; self.pan=[0.,0.]; self.draw()

    def draw(self):
        if self.destroyed: return
        canvas=self.canvas; canvas.delete('all')
        w,h=max(canvas.winfo_width(),100),max(canvas.winfo_height(),100)
        canvas.create_line(0,h/2,w,h/2,fill='#17384c'); canvas.create_line(w/2,0,w/2,h,fill='#17384c')
        overrides={}
        if self.preview.get():
            for part in self.scene['parts']:
                joint=part.get('joint')
                if joint: overrides[part['id']]=joint['min_deg']+(joint['max_deg']-joint['min_deg'])*(1+math.sin(self.phase))/2
        meshes=world_vertices(self.scene,overrides)
        all_points=[v for vertices,_ in meshes.values() for v in vertices]
        if not all_points:
            canvas.create_text(w/2,h/2,text='No measured geometry yet\nImport an assembly, add a part, or view the example.',fill='#8ccee9',justify='center')
            return
        low,high=bounds(all_points); center=[(a+b)/2 for a,b in zip(low,high)]
        extent=max(max(b-a for a,b in zip(low,high)),1)
        scale=min(w,h)*.65/extent*self.zoom
        for index,(pid,(vertices,edges)) in enumerate(meshes.items()):
            projected=[]
            for point in vertices:
                point=[point[i]-center[i] for i in range(3)]
                if self.exploded.get():
                    # Display-only spread. Saved assembly transforms stay untouched.
                    point[2]+=(index-(len(meshes)-1)/2)*extent*.25
                x,y,z=rotate(point,[self.pitch,0,self.yaw])
                projected.append((w/2+x*scale+self.pan[0],h/2-z*scale+self.pan[1]))
            color='#ffd978' if pid==self.selected else '#60daf5'
            for a,b in edges:
                canvas.create_line(*projected[a],*projected[b],fill=color,width=2 if pid==self.selected else 1,tags=('part',pid))
        canvas.create_text(10,12,text='Z ↑  |  WIRE-FRAME 3D  |  '+('KINEMATICS ONLY' if self.preview.get() else 'ASSEMBLY'),anchor='nw',fill='#87b6ce')

    def drag_start(self,event):
        self.last_drag=(event.x,event.y)
        items=self.canvas.find_closest(event.x,event.y,halo=8)
        if items:
            tags=self.canvas.gettags(items[0])
            if 'part' in tags:
                self.selected=tags[1]; self.describe(); self.draw()

    def drag(self,event):
        if self.last_drag:
            dx,dy=event.x-self.last_drag[0],event.y-self.last_drag[1]
            if event.state & 1: self.pan[0]+=dx; self.pan[1]+=dy
            else: self.yaw+=dx*.5; self.pitch+=dy*.5
            self.draw()
        self.last_drag=(event.x,event.y)

    def wheel(self,direction):
        self.zoom=max(.1,min(10,self.zoom*(1.1 if direction>0 else 1/1.1))); self.draw()

    def select_part(self,event=None):
        selection=self.parts.curselection()
        if selection: self.selected=self.parts.get(selection[0]); self.describe(); self.draw()

    def commit(self,scene,reason,expected_parent,editor=None):
        if not self.store: raise ValueError('Open a saved project first.')
        if self.busy: raise ValueError('A workspace operation is already running.')
        scene=validate(scene); store=self.store
        self.busy=True; self.status.configure(text='Checking candidate geometry…')
        def worker():
            try:
                tests=run_checks(scene, project_root=store.root if (store.root/'project.json').exists() else None)
                rid=store.add(scene,reason,[{'document':'User-authored local assembly'}],tests,
                              expected_parent=expected_parent,as_input=True)
                self.results.put(('saved',store.root,store.revision(rid),editor))
            except Exception as error: self.results.put(('error',store.root,str(error),None))
        threading.Thread(target=worker,daemon=True).start()

    def edit_base(self):
        return self.revision['id'] if self.revision else None

    def import_scene(self):
        base=self.edit_base()
        path=filedialog.askopenfilename(parent=self,title='Import measured assembly JSON',filetypes=[('Assembly JSON','*.json')])
        if not path: return
        try: self.commit(load(path),'User imported an explicit assembly; dimensions remain source-reported.',base)
        except Exception as error: messagebox.showerror('Assembly import',str(error),parent=self)

    def edit_scene(self):
        if self.demo_mode:
            messagebox.showinfo('Example','Return to Latest before editing your project.',parent=self); return
        base=self.edit_base()
        window=tk.Toplevel(self); window.title('Edit explicit geometry JSON (mm)'); window.geometry('720x600')
        text=tk.Text(window,wrap='none'); text.pack(fill='both',expand=True); text.insert('end',json.dumps(self.scene,indent=2))
        def save():
            try:
                scene=json.loads(text.get('1.0','end'))
                if scene.get('requirements'): scene['requirements']['origin']='user_authored'
                self.commit(scene,'User edited explicit part geometry.',base,window)
            except Exception as error: messagebox.showerror('Invalid assembly',str(error),parent=window)
        ttk.Button(window,text='Validate and save candidate',command=save).pack()


    def edit_printer(self):
        if not self.project:
            messagebox.showinfo('Printer profile','Open a saved project first.',parent=self); return
        project=self.project
        from fabrication.printer_fit import PrinterFitStore, PROFILE_FORMAT
        from inventory.equipment import load_all
        try:
            fit_store=PrinterFitStore(project)
            selection=fit_store.selection()
            opening_project_revision=fit_store._project()[1]
            inventory=load_all(strict_ids=True)
            ids=[item['equipment_id'] for item in inventory['items']
                 if item.get('category')=='3d_printer' and item.get('equipment_id')]
        except Exception as error:
            messagebox.showerror('Printer profile',str(error),parent=self); return
        window=tk.Toplevel(self); window.title('Project printer geometry profile')
        window.geometry('720x600')
        ttk.Label(window,text='Choose an inventory ID and explicitly review usable millimetres, margins and rectangular keep-outs. Geometry only.').pack(fill='x')
        chosen=tk.StringVar(value=selection['printer_id'] if selection else '')
        ttk.Combobox(window,textvariable=chosen,values=ids,state='readonly').pack(fill='x')
        text=tk.Text(window,wrap='word'); text.pack(fill='both',expand=True)
        profile=selection['profile'] if selection else {
            'format':PROFILE_FORMAT,'units':'mm','usable_xyz':None,
            'margins_min_xyz':None,'margins_max_xyz':None,'keep_outs':[],
            'review':{'reviewer':'','note':''}}
        text.insert('end',json.dumps(profile,indent=2))
        ttk.Label(window,text='Each part also needs printer_placement in Edit scene: units mm, min_xyz and orientation xyz/xzy/yxz/yzx/zxy/zyx. No placement is inferred.').pack(fill='x')
        expected=selection['revision'] if selection else 0
        def save():
            try:
                if self.project != project or fit_store._project()[1]!=opening_project_revision:
                    raise ValueError('Active project or its revision changed; reopen the printer editor.')
                profile=json.loads(text.get('1.0','end'))
                fit_store.select(chosen.get(),profile,expected_revision=expected,
                                 expected_project_revision=opening_project_revision)
                queue_refresh(project); window.destroy(); self.describe()
            except Exception as error:
                messagebox.showerror('Printer profile',str(error),parent=window)
        ttk.Button(window,text='Save explicitly reviewed geometry profile',command=save).pack()

    def edit_requirements(self):
        if self.demo_mode: self.show_latest()
        from .requirements import manifest
        base=self.edit_base()
        window=tk.Toplevel(self); window.title('Custom idea requirements and research questions'); window.geometry('760x620')
        ttk.Label(window,text='Edit goals, subsystem dependencies and research questions. These are requirements, not validated facts.').pack(fill='x')
        text=tk.Text(window,wrap='word'); text.pack(fill='both',expand=True)
        text.insert('end',json.dumps(self.scene.get('requirements') or manifest({}),indent=2))
        def save():
            try:
                value=json.loads(text.get('1.0','end')); value['origin']='user_authored'
                scene=copy.deepcopy(self.scene); scene['requirements']=value
                self.commit(scene,'User refined custom requirements and research questions.',base,window)
            except Exception as error: messagebox.showerror('Invalid requirements',str(error),parent=window)
        ttk.Button(window,text='Save requirements candidate',command=save).pack()

    def add_part(self):
        if self.demo_mode: self.show_latest()
        base=self.edit_base()
        specification=simpledialog.askstring('Add measured box','Enter: id, width_mm, depth_mm, height_mm, x_mm, y_mm, z_mm\nCoordinates are absolute unless you later set a parent in Edit scene.',parent=self)
        if not specification: return
        try:
            values=[x.strip() for x in specification.split(',')]
            if len(values)!=7: raise ValueError('Enter one ID and six numbers.')
            scene=copy.deepcopy(self.scene)
            scene['parts'].append({'id':values[0],'shape':'box','size_mm':[float(x) for x in values[1:4]],
                                   'position_mm':[float(x) for x in values[4:7]],'rotation_deg':[0,0,0],
                                   'provenance':{'status':'user_supplied','source':'Dimensions explicitly entered in workspace; not physically validated.'}})
            self.commit(scene,'User added a measured part.',base)
        except Exception as error: messagebox.showerror('Add part',str(error),parent=self)

    def accept(self):
        if self.demo_mode or not self.revision: return
        self.store.accept(self.revision['id']); self.describe()

    def restore(self):
        revision=self.selected_revision()
        if revision:
            try: self.commit(revision['scene'],'Restored historical revision '+revision['id'][:8]+' as a new candidate.',self.store.pointer())
            except Exception as error: messagebox.showerror('Restore',str(error),parent=self)

    def test_scene(self):
        if self.busy: return
        self.busy=True; scene=copy.deepcopy(self.scene); project=self.project
        self.status.configure(text='Running bounded geometric checks…')
        def worker():
            try: self.results.put(('tested',project,run_checks(scene, project_root=project if project and (project/'project.json').exists() else None),None))
            except Exception as error: self.results.put(('error',project,str(error),None))
        threading.Thread(target=worker,daemon=True).start()

    def tick(self):
        if self.destroyed: return
        try:
            while True:
                kind,project,value,editor=self.results.get_nowait()
                self.busy=False
                if project != self.project: continue
                if kind=='error': messagebox.showerror('Workspace operation',value,parent=self)
                elif kind=='saved':
                    self.demo_mode=False; self.install(value['scene'],value); self.refresh_history()
                    if editor and editor.winfo_exists(): editor.destroy()
                elif kind=='tested':
                    if value['scene_hash']==digest(self.scene): self.describe(value)
                    else: self.status.configure(text='Scene changed during checks; run checks again for the visible revision.')
        except queue.Empty: pass
        if self.preview.get(): self.phase+=.08; self.draw()
        if self.store and not self.demo_mode:
            latest=self.store.pointer()
            # New proposals should become visible, but preserve deliberate historical previews.
            if latest != getattr(self,'last_seen_latest',None):
                self.last_seen_latest=latest; self.show_latest()
        self.timer=self.after(150,self.tick)


def open_window(master, root):
    window=tk.Toplevel(master); window.title('3D assembly workspace'); window.geometry('1250x750')
    Workspace(window,root).pack(fill='both',expand=True)
    return window
