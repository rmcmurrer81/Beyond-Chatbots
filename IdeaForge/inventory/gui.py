from __future__ import annotations
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from inventory.equipment import load_all, remember

CATS=["3d_printer","computer","gpu","vr","camera","audio","electronics_tool","mechanical_tool","measurement_tool","fabrication_tool","robotics_hardware","other"]

def main():
    app=tk.Tk(); app.title("IdeaForge — My Equipment"); app.geometry("920x580")
    f=ttk.Frame(app,padding=12); f.pack(fill="both",expand=True)
    ttk.Label(f,text="My Equipment",font=("Segoe UI",18,"bold")).pack(anchor="w")
    ttk.Label(f,text="IdeaForge checks this list before suggesting tools or deciding how to prototype something.").pack(anchor="w",pady=(0,8))
    tree=ttk.Treeview(f,columns=("category","item","qty","source"),show="headings")
    for c,t,w in [("category","Category",140),("item","Item / model",500),("qty","Qty",60),("source","Source",140)]:
        tree.heading(c,text=t); tree.column(c,width=w,anchor="w")
    tree.pack(fill="both",expand=True)

    def refresh():
        for x in tree.get_children(): tree.delete(x)
        for i in load_all().get("items",[]):
            label=i.get("name","")
            if i.get("model") and str(i["model"]).lower() not in label.lower(): label += " — "+str(i["model"])
            tree.insert("","end",values=(i.get("category",""),label,i.get("quantity",1),"Humanoid Researcher" if i.get("imported_from") else "IdeaForge"))

    def add():
        name=simpledialog.askstring("Add equipment","What do you own?")
        if not name: return
        cat=simpledialog.askstring("Category","Category:\n"+", ".join(CATS),initialvalue="other") or "other"
        if cat not in CATS:
            messagebox.showerror("Category","Use one of the listed categories."); return
        maker=simpledialog.askstring("Manufacturer","Manufacturer (optional):")
        model=simpledialog.askstring("Model","Exact model (optional):")
        remember({"name":name,"category":cat,"manufacturer":maker,"model":model,"ownership_status":"owned"})
        refresh()

    bar=ttk.Frame(f); bar.pack(fill="x",pady=(8,0))
    ttk.Button(bar,text="Add equipment",command=add).pack(side="left")
    ttk.Button(bar,text="Refresh",command=refresh).pack(side="left",padx=(8,0))
    refresh(); app.mainloop()

if __name__=="__main__": main()
