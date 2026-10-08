from __future__ import annotations
import json, os, queue, subprocess, sys, threading, time, tkinter as tk, webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, simpledialog
try:
    from PIL import Image, ImageTk, ImageGrab
except Exception:
    Image=None
    ImageTk=None
    ImageGrab=None

from ai.chat import IdeaForgeChat
from ai.hands_free import HandsFreeChat, voice_prompt
from core.project_index import list_projects
from core.project_state import load as load_project_state

def _load_json(path,default=None):
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default

def main(chat_factory=IdeaForgeChat,controller_factory=None):
    cfg=json.loads(Path("ai/config.json").read_text(encoding="utf-8"))
    chat=chat_factory()

    app=tk.Tk()
    app.title("Kira Labs IdeaForge")
    app.geometry("1500x850")
    app.minsize(1000,700)

    top=ttk.Frame(app,padding=(10,8))
    top.pack(fill="x")
    ttk.Label(top,text="Kira Labs IdeaForge",font=("Segoe UI",20,"bold")).pack(side="left")
    provider_label=ttk.Label(top,text=f"AI: {chat.model_name} • Voice separate")
    provider_label.pack(side="right")

    notification_project={"path":None}
    notification_frame=ttk.Frame(app,padding=(10,5))
    notification_var=tk.StringVar(value="")
    notification_label=ttk.Label(notification_frame,textvariable=notification_var,wraplength=1180)
    notification_label.pack(side="left",fill="x",expand=True)
    def open_notification_project():
        if notification_project.get("path"):
            submit_text(f"open {Path(notification_project['path']).name} project")
            notification_frame.pack_forget()
    ttk.Button(notification_frame,text="Open Project",command=open_notification_project).pack(side="right",padx=(8,0))
    ttk.Button(notification_frame,text="Dismiss",command=notification_frame.pack_forget).pack(side="right")
    notification_frame.pack_forget()

    mainpane=ttk.Panedwindow(app,orient="horizontal")
    mainpane.pack(fill="both",expand=True,padx=10,pady=(0,10))

    # LEFT: PROJECTS
    left=ttk.Frame(mainpane,padding=8)
    mainpane.add(left,weight=1)
    ttk.Label(left,text="Projects",font=("Segoe UI",14,"bold")).pack(anchor="w")
    project_tree=ttk.Treeview(left,columns=("view","research","new"),show="tree headings",height=20)
    project_tree.heading("#0",text="Project")
    project_tree.heading("view",text="View")
    project_tree.heading("research",text="Research")
    project_tree.heading("new",text="New")
    project_tree.column("#0",width=110)
    project_tree.column("view",width=40)
    project_tree.column("research",width=60)
    project_tree.column("new",width=30)
    project_tree.pack(fill="both",expand=True,pady=(6,6))

    left_buttons=ttk.Frame(left)
    left_buttons.pack(fill="x")
    left_buttons.columnconfigure((0,1),weight=1)
    ttk.Button(left_buttons,text="New",command=lambda:new_project_dialog()).grid(row=0,column=0,sticky="ew",padx=2,pady=2)
    ttk.Button(left_buttons,text="Open",command=lambda:open_selected_project()).grid(row=0,column=1,sticky="ew",padx=2,pady=2)
    ttk.Button(left_buttons,text="Close",command=lambda:submit_text("close this project")).grid(row=1,column=0,sticky="ew",padx=2,pady=2)
    ttk.Button(left_buttons,text="Research",command=lambda:submit_text("research this project")).grid(row=1,column=1,sticky="ew",padx=2,pady=2)

    research_note=ttk.Label(left,text="Background research keeps running when you switch/close a project view.",wraplength=220)
    research_note.pack(anchor="w",pady=(8,0))

    def show_assembly_workspace():
        if not chat.current_project:
            messagebox.showinfo("3D workspace", "Open a saved project first."); return
        from workspace3d.viewer import open_window
        open_window(app, chat.current_project)

    ttk.Button(left, text="3D Assembly Workspace", command=show_assembly_workspace).pack(fill="x", pady=(6, 0))

    # CENTER: CHAT
    center=ttk.Frame(mainpane,padding=8)
    mainpane.add(center,weight=3)
    current_label=ttk.Label(center,text="Current project: none",font=("Segoe UI",13,"bold"),wraplength=360)
    current_label.pack(anchor="w")

    output=tk.Text(center,width=1,height=1,wrap="word",state="disabled")
    output.pack(fill="both",expand=True,pady=(6,0))

    status=ttk.Label(center,text="Ready")
    status.pack(anchor="w",pady=(6,0))

    attachment={"path":None}
    attachbar=ttk.Frame(center)
    attachbar.pack(fill="x",pady=(6,0))
    attach_label=ttk.Label(attachbar,text="No troubleshooting image attached",wraplength=320)
    attach_label.pack(fill="x",anchor="w")

    def set_attachment(path):
        attachment["path"]=str(path) if path else None
        attach_label.configure(text=f"Attached: {Path(path).name}" if path else "No troubleshooting image attached")

    def choose_image():
        p=filedialog.askopenfilename(
            title="Attach troubleshooting photo or screenshot",
            filetypes=[("Images","*.png *.jpg *.jpeg *.webp"),("PNG","*.png"),("JPEG","*.jpg *.jpeg"),("WEBP","*.webp")]
        )
        if p: set_attachment(p)

    def paste_screenshot():
        if ImageGrab is None:
            messagebox.showinfo("Paste Screenshot","Pillow/ImageGrab is unavailable. Use Attach Image instead.")
            return
        try:
            clip=ImageGrab.grabclipboard()
            if clip is None:
                messagebox.showinfo("Paste Screenshot","There is no image on the clipboard.")
                return
            if isinstance(clip,list):
                for p in clip:
                    if Path(p).suffix.lower() in {".png",".jpg",".jpeg",".webp"}:
                        set_attachment(p); return
                messagebox.showinfo("Paste Screenshot","Clipboard contains files but no supported image.")
                return
            out=Path("chat_attachments"); out.mkdir(parents=True,exist_ok=True)
            p=out/f"troubleshooting-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.png"
            clip.save(p,"PNG"); set_attachment(p)
        except Exception as e:
            messagebox.showerror("Paste Screenshot",str(e))

    attachment_buttons=ttk.Frame(attachbar)
    attachment_buttons.pack(fill="x",pady=(3,0))
    attachment_buttons.columnconfigure((0,1,2),weight=1)
    ttk.Button(attachment_buttons,text="Attach Image",command=choose_image).grid(row=0,column=0,sticky="ew",padx=2)
    ttk.Button(attachment_buttons,text="Paste Screenshot",command=paste_screenshot).grid(row=0,column=1,sticky="ew",padx=2)
    ttk.Button(attachment_buttons,text="Clear",command=lambda:set_attachment(None)).grid(row=0,column=2,sticky="ew",padx=2)

    bottom=ttk.Frame(center)
    bottom.pack(fill="x",pady=(6,0))
    entry=tk.Text(bottom,width=1,height=4,wrap="word")
    send=ttk.Button(bottom,text="Send")
    # Reserve the primary action before the expanding editor consumes the row.
    send.pack(side="right",padx=(8,0),fill="y")
    entry.pack(side="left",fill="x",expand=True)

    controls=ttk.Frame(center)
    controls.pack(fill="x",pady=(6,0))
    controls.columnconfigure((0,1,2),weight=1)
    hands=ttk.Button(controls,text="Start Hands-Free")
    hands.grid(row=0,column=0,sticky="ew",padx=2,pady=2)
    stop_voice=ttk.Button(controls,text="Stop",state="disabled")
    stop_voice.grid(row=0,column=1,sticky="ew",padx=2,pady=2)
    mute_voice=tk.BooleanVar(value=False)
    ttk.Checkbutton(controls,text="Mute AI voice",variable=mute_voice).grid(row=0,column=2,sticky="w",padx=2,pady=2)
    ttk.Button(controls,text="My Equipment",command=lambda:subprocess.Popen([sys.executable,"-m","inventory.gui"])).grid(row=1,column=0,sticky="ew",padx=2,pady=2)
    ttk.Button(controls,text="Prototype",command=lambda:submit_text("Make a prototype for this project")).grid(row=1,column=1,sticky="ew",padx=2,pady=2)
    ttk.Button(controls,text="Simulation",command=lambda:submit_text("Create a simulation plan for this project")).grid(row=1,column=2,sticky="ew",padx=2,pady=2)
    voice_status=ttk.Label(center,text="Hands-free off — microphone not listening",wraplength=360)
    voice_status.pack(anchor="w",pady=(4,0))
    voice_name=ttk.Label(center,text="Female Windows voice (not checked)",wraplength=360)
    voice_name.pack(anchor="w")

    # RIGHT: DETAILS + IMAGES
    right=ttk.Frame(mainpane,padding=8)
    mainpane.add(right,weight=2)
    ttk.Label(right,text="Project Details & References",font=("Segoe UI",14,"bold"),wraplength=220).pack(anchor="w")

    details=tk.Text(right,width=26,height=17,wrap="word",state="disabled")
    details.pack(fill="x",pady=(6,6))

    gallery_canvas=tk.Canvas(right,width=1,height=420,highlightthickness=0)
    gallery_scroll=ttk.Scrollbar(right,orient="vertical",command=gallery_canvas.yview)
    gallery_frame=ttk.Frame(gallery_canvas)
    gallery_frame.bind("<Configure>",lambda e:gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all")))
    gallery_canvas.create_window((0,0),window=gallery_frame,anchor="nw")
    gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
    gallery_canvas.pack(side="left",fill="both",expand=True)
    gallery_scroll.pack(side="right",fill="y")
    gallery_images=[]

    events=queue.Queue()
    chat.research_manager.event_callback=lambda kind,payload: events.put(("research_event",(kind,payload)))
    last_workspace_signature={"value":None}
    project_rows={}

    def add(who,text):
        output.configure(state="normal")
        output.insert("end",f"\n{who}\n{text}\n")
        output.see("end")
        output.configure(state="disabled")

    def answer_worker(text,turn,image_path=None):
        try:
            answer=chat.ask(text,image_path=image_path)
            events.put(("answer",(turn,answer)))
        except Exception as e:
            events.put(("error",(turn,str(e))))

    def submit_text(text=None,from_voice=False,turn=None):
        text=(text if text is not None else entry.get("1.0","end")).strip()
        if not text: return
        if turn is None:
            turn=voice.begin_turn()
        if turn is None or voice.closed: return
        image_path=None if from_voice else attachment["path"]
        if not from_voice: entry.delete("1.0","end")
        shown=text+(f"\n[Attached image: {Path(image_path).name}]" if image_path else "")
        add("You",shown)
        send.configure(state="disabled")
        status.configure(text="Troubleshooting…" if image_path else "Thinking…")
        if image_path: set_attachment(None)
        threading.Thread(target=answer_worker,args=(text,turn,image_path),daemon=True).start()

    def on_voice_prompt(text,turn):
        prompt=voice_prompt(text,cfg.get("hands_free",{}))
        if prompt:
            submit_text(prompt,True,turn)
        else:
            voice.finish_turn(turn,"cancelled")

    def voice_changed():
        if voice.closed: return
        hands.configure(state="disabled" if voice.enabled or voice.start_blocked else "normal")
        stop_voice.configure(state="normal" if voice.enabled else "disabled")
        send.configure(state="disabled" if voice.blocked else "normal")
        label=("Voice shutdown pending" if voice.retiring is not None else
               f"Hands-free {voice.state}" if voice.enabled else
               "Hands-free off — microphone not listening")
        voice_status.configure(text=label)
        voice_name.configure(text=voice.voice_label)

    voice_options={} if controller_factory is None else {"controller_factory":controller_factory}
    voice=HandsFreeChat(events.put,on_voice_prompt,voice_changed,
                       lambda message:add("Voice",message),**voice_options)

    def new_project_dialog():
        idea=simpledialog.askstring("New IdeaForge Project","What do you want to build, recreate, or invent?")
        if idea:
            submit_text("start a new project "+idea)

    def open_selected_project():
        sel=project_tree.selection()
        if not sel:
            messagebox.showinfo("IdeaForge","Select a project first."); return
        path=project_rows.get(sel[0])
        if path is None:
            messagebox.showinfo("IdeaForge","Refresh the project list and select a project again."); return
        submit_text(f"open {Path(path).name} project")

    def on_project_double_click(event=None):
        open_selected_project()

    project_tree.bind("<Double-1>",on_project_double_click)

    def open_project_folder():
        if not chat.current_project:
            messagebox.showinfo("IdeaForge","No project is open."); return
        try: os.startfile(chat.current_project)
        except Exception as e: messagebox.showerror("IdeaForge",str(e))

    ttk.Button(left_buttons,text="Folder",command=open_project_folder).grid(row=2,column=0,columnspan=2,sticky="ew",padx=2,pady=2)

    def render_details():
        root=Path(chat.current_project) if chat.current_project else None
        current_label.configure(text=f"Current project: {chat.current_project_name or 'none'}")
        details.configure(state="normal"); details.delete("1.0","end")
        if not root:
            details.insert("end","No project is currently open.\n\nYou can start another project while closed projects continue background research.")
            details.configure(state="disabled")
            render_gallery(None)
            return
        project=_load_json(root/"project.json",{}) or {}
        state=load_project_state(root)
        plan=project.get("plan",{}) or {}
        lines=[
            f"Name: {project.get('name',root.name)}",
            f"Project ID / folder: {root.name}",
            f"Status: {project.get('status','concept')}",
            f"Research: {state.get('research_status','idle')}",
            f"Continuous watch: {'ON' if state.get('research_watch_enabled',True) else 'OFF'}",
            f"New discoveries: {state.get('unread_discoveries',0)}",
        ]
        if state.get("last_message"): lines.append(state["last_message"])
        lines += ["",plan.get("summary","")]
        if plan.get("visual_reference_target"):
            lines += ["",f"Visual target: {plan.get('visual_reference_target')}"]
        if plan.get("build_type_options"):
            lines += ["","Build types: "+", ".join(plan.get("build_type_options",[]))]
        if plan.get("subsystems"):
            lines += ["","Subsystems:"]+[f"• {x}" for x in plan.get("subsystems",[])[:8]]
        variants=_load_json(root/"research"/"reference_variants.json",{}) or {}
        if variants.get("selection_needed") and variants.get("variants"):
            lines += ["","Design variants:"]
            for i,v in enumerate(variants["variants"],1):
                lines.append(f"{i}. {v.get('label','Variant')} — {v.get('description','')}")
            lines.append(variants.get("question") or "Say “use variant 1” or choose a reference image.")
        selected=_load_json(root/"design"/"selected_reference.json",{}) or {}
        if selected:
            lines += ["","Selected reference:"]
            if selected.get("variant"): lines.append(selected["variant"].get("label","Selected variant"))
            if selected.get("image"): lines.append(f"Image {selected['image'].get('index')}: {selected['image'].get('title')}")
        virtual=_load_json(root/"design"/"virtual_concepts.json",{}) or {}
        current=virtual.get("current_buildable_concept") or {}
        if current.get("summary"):
            lines += ["","Virtual build — what can be built now:",current.get("summary","")]
            for x in current.get("limitations",[])[:4]:
                lines.append(f"• Limitation: {x}")
        discoveries_path=root/"research"/"LATEST_DISCOVERIES.md"
        if discoveries_path.exists():
            lines += ["","Useful discoveries are available in research/LATEST_DISCOVERIES.md"]
        details.insert("end","\n".join(lines))
        details.configure(state="disabled")
        render_gallery(root)

    def render_gallery(root):
        for child in gallery_frame.winfo_children(): child.destroy()
        gallery_images.clear()
        if not root:
            ttk.Label(gallery_frame,text="Reference images will appear here after research.",wraplength=200).pack(anchor="w")
            return
        gallery=_load_json(Path(root)/"research"/"gallery.json",{}) or {}
        images=gallery.get("images",[])[:8]
        if not images:
            ttk.Label(gallery_frame,text="No reference images yet. Research may still be running.",wraplength=200).pack(anchor="w")
            return
        for item in images:
            card=ttk.Frame(gallery_frame,padding=5,relief="ridge")
            card.pack(fill="x",pady=4)
            local=item.get("local_file")
            if local and Path(local).exists() and Image and ImageTk:
                try:
                    im=Image.open(local).convert("RGB")
                    im.thumbnail((200,170))
                    photo=ImageTk.PhotoImage(im)
                    gallery_images.append(photo)
                    lbl=ttk.Label(card,image=photo)
                    lbl.pack(anchor="center")
                except Exception:
                    pass
            title=f"Image {item.get('index')}: {item.get('title','Reference')}"
            ttk.Label(card,text=title,wraplength=200).pack(anchor="w")
            row=ttk.Frame(card); row.pack(fill="x",pady=(3,0))
            ttk.Button(row,text="Use this",command=lambda n=item.get("index"):submit_text(f"use image {n}")).pack(side="left")
            if item.get("page_url"):
                ttk.Button(row,text="Source",command=lambda u=item.get("page_url"):webbrowser.open(u)).pack(side="left",padx=(5,0))

    def refresh_workspace(force=False):
        try: provider_label.configure(text=f"AI: {chat.model_name} • Voice separate")
        except Exception: provider_label.configure(text="AI: provider configuration invalid • Voice separate")
        items=list_projects()
        signature=(
            str(chat.current_project) if chat.current_project else None,
            tuple((str(x["path"]),x.get("view_status"),x.get("research_status"),x.get("unread_discoveries"),x.get("last_discovery_at"),x.get("modified")) for x in items)
        )
        if not force and signature==last_workspace_signature["value"]:
            return
        last_workspace_signature["value"]=signature
        sel=project_tree.selection()
        selected_path=project_rows.get(sel[0]) if sel else None
        for x in project_tree.get_children(): project_tree.delete(x)
        project_rows.clear()
        active_path=Path(chat.current_project) if chat.current_project else None
        known_paths={Path(x["path"]) for x in items}
        selection_target=selected_path if selected_path in known_paths else active_path
        for item in items:
            iid=project_tree.insert("","end",text=item["name"],values=(
                "ACTIVE" if active_path and Path(item["path"])==active_path else item.get("view_status","closed"),
                item.get("research_status","idle"),
                item.get("unread_discoveries",0) or ""
            ))
            project_rows[iid]=Path(item["path"])
            if selection_target is not None and Path(item["path"])==selection_target:
                project_tree.selection_set(iid)
        render_details()

    def project_name_from_path(path):
        data=_load_json(Path(path)/"project.json",{}) or {}
        return data.get("name") or Path(path).name

    def show_discovery_notification(payload):
        name=project_name_from_path(payload.get("project",""))
        discoveries=payload.get("discoveries",[]) or []
        topd=discoveries[0] if discoveries else {}
        title=topd.get("title","Useful discovery")
        why=topd.get("why_useful","")
        notification_project["path"]=payload.get("project")
        notification_var.set(f"Discovery for {name}: {title}" + (f" — {why}" if why else ""))
        notification_frame.pack(fill="x",after=top)
        try: app.bell()
        except Exception: pass
        add("IdeaForge Discovery",f"{name}: {title}" + (f"\n{why}" if why else ""))

    def pump():
        if voice.closed: return
        voice.poll_retirement()
        try:
            while True:
                kind,payload=events.get_nowait()
                if kind=="status":
                    status.configure(text=payload)
                elif kind=="voice":
                    voice.handle_event(*payload)
                elif kind=="answer":
                    turn,answer=payload
                    if voice.current_turn!=turn: continue
                    add("IdeaForge",answer)
                    voice.finish_turn(turn,"answer","" if mute_voice.get() else answer)
                    refresh_workspace(force=True)
                    status.configure(text="Ready")
                elif kind=="research_event":
                    event_kind,event_payload=payload
                    if event_kind=="useful_discovery":
                        show_discovery_notification(event_payload)
                    elif event_kind=="research_complete":
                        status.configure(text="Background research completed")
                    elif event_kind=="research_error":
                        status.configure(text="Background research error")
                    refresh_workspace(force=True)
                elif kind=="error":
                    turn,message=payload
                    if voice.current_turn!=turn: continue
                    add("ERROR",message)
                    voice.finish_turn(turn,"error")
                    status.configure(text="Ready")
        except queue.Empty:
            pass
        refresh_workspace()
        app.after(500,pump)

    send.configure(command=lambda:submit_text())
    hands.configure(command=voice.start)
    stop_voice.configure(command=voice.stop)
    entry.bind("<Control-Return>",lambda e:(submit_text(),"break")[1])

    add("IdeaForge","You can work on several projects. Say “close this project,” “open my R2-D2 project,” “start another project,” “show my projects,” or choose displayed references with “use variant 2” / “use image 4.” Background research continues while IdeaForge is running.")
    refresh_workspace(force=True)
    app.after(120,pump)

    def shutdown():
        voice.close()
        if hasattr(chat,"close"): chat.close()
        elif hasattr(chat,"cancel_pending"): chat.cancel_pending()
        try: chat.research_manager.shutdown()
        except Exception: pass
        app.destroy()

    app.protocol("WM_DELETE_WINDOW",shutdown)
    app.mainloop()

if __name__=="__main__":
    main()
