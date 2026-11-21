"""Graphical Linux installer, launched from a checksum-verified release archive."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
from zipfile import ZipFile

FAMILIES = ("Krea 2 Raw", "Anima Base", "Illustrious XL v0.1")
VISION = ("Qwen3-VL", "JoyCaption Beta One")
DOWNLOAD = "Download the suggested model"
LOCAL = "Use a model on this PC"
URL = "Use a Hugging Face file link"
LATER = "Set up later"


def data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home()/".local/share")


def destination(value):
    root = Path(value).expanduser()
    if not value.strip() or not root.is_absolute() or root == Path("/") or any(ord(c)<32 for c in str(root)):
        raise ValueError("Choose an absolute installation folder.")
    if root.exists() and (not root.is_dir() or any(root.iterdir()) and not (root/"app/inicio.py").is_file()):
        raise ValueError("Choose an empty folder or an existing HydraTrainStudio installation.")
    return root.resolve()


def shortcuts(root, plan):
    folders = []
    if plan["menu"] == "True":
        folders.append(data_home()/"applications")
    if plan["desktop"] == "True":
        desktop = Path.home()/"Desktop"
        if shutil.which("xdg-user-dir"):
            result = subprocess.run(["xdg-user-dir","DESKTOP"],capture_output=True,text=True,check=True)
            desktop = Path(result.stdout.strip())
        if not desktop.is_absolute() or desktop == Path.home():
            raise ValueError("The desktop folder is disabled. Clear Desktop shortcut and try again.")
        folders.append(desktop)
    # Desktop entries have separate escaping rules for string and Exec arguments.
    script = str(root/"abrir-linux.sh").replace("%","%%")
    quoted = "".join("\\"+c if c in '\\"$`' else c for c in script)
    icon = str(root/"HydraTrainStudio_Assets/branding/hydra_symbol_128.png")
    entry = ('[Desktop Entry]\nType=Application\nName=HydraTrainStudio\nExec=bash "'+
             quoted.replace("\\","\\\\")+'"\nIcon='+icon.replace("\\","\\\\")+
             '\nTerminal=false\nCategories=Graphics;\n')
    for folder in folders:
        folder.mkdir(parents=True,exist_ok=True)
        file = folder/"hydratrainstudio.desktop"
        file.write_text(entry,encoding="utf8")
        file.chmod(0o755)


def install(archive,plan,status):
    root = destination(plan["folder"])
    root.mkdir(parents=True,exist_ok=True)
    status("Extracting the verified application package...")
    with ZipFile(archive) as package:
        for member in package.infolist():
            dest = root/member.filename
            if dest.resolve()!=dest or not dest.is_relative_to(root):
                raise ValueError("Unsafe installation path: "+str(dest))
            package.extract(member,root)
    launcher = root/"abrir-linux.sh"
    launcher.chmod(0o755)
    logs = root/"dados/logs"
    logs.mkdir(parents=True,exist_ok=True)
    log = logs/"setup-linux.log"
    status("Installing Python libraries and selected components. Details: "+str(log))
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp)/"choices.json"
        file.write_text(json.dumps(plan),encoding="utf8")
        with log.open("a",encoding="utf8") as out:
            result = subprocess.run(["bash",str(launcher),"--setup-plan",str(file)],stdout=out,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError("Installation interrupted. See "+str(log))
    shortcuts(root,plan)
    return launcher


class Wizard:
    pages=("Welcome","Destination","Training models","Automatic captions","Test images","Shortcuts","Review")
    def __init__(self,window,archive):
        self.win=window
        self.archive=archive
        self.index=0
        self.vars={}
        self.busy=False
        self.launcher=None
        self.events=queue.Queue()
        window.title("HydraTrainStudio Setup")
        window.geometry("800x590")
        window.minsize(480,380)
        window.protocol("WM_DELETE_WINDOW",self.close)
        self.title=ttk.Label(window,font=("TkDefaultFont",18,"bold"),padding=16)
        self.title.pack(anchor="w")
        footer=ttk.Frame(window,padding=10)
        footer.pack(side="bottom",fill="x")
        self.next=ttk.Button(footer,command=self.advance)
        self.next.pack(side="right")
        self.back=ttk.Button(footer,text="Back",command=self.previous)
        self.back.pack(side="right",padx=6)
        self.cancel=ttk.Button(footer,text="Cancel",command=self.close)
        self.cancel.pack(side="left")
        self.canvas=tk.Canvas(window,highlightthickness=0)
        bar=ttk.Scrollbar(window,command=self.canvas.yview)
        bar.pack(side="right",fill="y")
        self.canvas.pack(fill="both",expand=True)
        self.canvas.configure(yscrollcommand=bar.set)
        self.body=ttk.Frame(self.canvas,padding=16)
        item=self.canvas.create_window(0,0,window=self.body,anchor="nw")
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(item,width=e.width))
        self.body.bind("<Configure>",lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.render()

    def var(self,key,default=""):
        if key not in self.vars:
            self.vars[key]=tk.StringVar(value=default)
        return self.vars[key]

    def note(self,msg):
        ttk.Label(self.body,text=msg,wraplength=max(360,self.canvas.winfo_width()-50)).pack(anchor="w",pady=5)

    def toggle(self,key,name,default="False"):
        ttk.Checkbutton(self.body,text=name,variable=self.var(key,default),onvalue="True",offvalue="False",command=self.render).pack(anchor="w")

    def field(self,key,label,default="",folder=False,url=False):
        self.note(label)
        row=ttk.Frame(self.body)
        row.pack(fill="x")
        v=self.var(key,default)
        ttk.Entry(row,textvariable=v).pack(side="left",expand=True,fill="x")
        def browse():
            selected=(filedialog.askdirectory if folder else filedialog.askopenfilename)(parent=self.win)
            if selected:v.set(selected)
        if not url:ttk.Button(row,text="Browse...",command=browse).pack(side="right")

    def models(self,items):
        return [m for m in items if self.var("select:"+m,"True" if m==items[0] else "False").get()=="True"]

    def source(self,key,label,suffix,optional=False,vision=False):
        self.note(label)
        mode=self.var(key,DOWNLOAD)
        box=ttk.Combobox(self.body,state="readonly",textvariable=mode,values=[DOWNLOAD,LOCAL,URL]+([LATER] if optional else []))
        box.pack(fill="x")
        box.bind("<<ComboboxSelected>>",lambda e:self.render())
        if mode.get() in (LOCAL,URL):
            remote=mode.get()==URL
            for tail in ([""," projector"] if vision else [""]):
                k=key+mode.get()+tail
                self.field(k,("Matching projector" if tail else "Model")+(" URL" if remote else " file"),url=remote)
                self.inputs.append((k,suffix,remote))

    def render(self):
        self.inputs=[]
        for child in self.body.winfo_children():child.destroy()
        self.canvas.yview_moveto(0)
        page=self.pages[self.index]
        self.title.configure(text=page)
        self.back.configure(state="normal" if self.index else "disabled")
        self.next.configure(text="Install" if page=="Review" else "Next")
        if page=="Welcome":
            self.note("Set up HydraTrainStudio for your Linux account. Choose the tools and models you need. For Studio alone, clear all model selections.")
        elif page=="Destination":
            self.note("Choose an empty folder, type a new folder name, or update an existing Studio installation.")
            self.field("folder","Installation folder",str(data_home()/"HydraTrainStudio"),folder=True)
        elif page in ("Training models","Automatic captions"):
            vision=page=="Automatic captions"
            items=VISION if vision else FAMILIES
            self.note("Choose any vision models for automatic captions. Each needs a matching projector." if vision else "Choose training families. Local files and alternative downloads must match the official training weights.")
            selected=self.models(items)
            for m in items:self.toggle("select:"+m,m)
            for m in selected:self.source(m,m,".gguf" if vision else ".safetensors",vision=vision)
        elif page=="Test images":
            selected=self.models(FAMILIES)
            self.note("Choose a compatible test model for each family. ComfyUI generates your comparison images." if selected else "No training families selected. You can configure testing later.")
            for m in selected:self.source("test:"+m,"Krea 2 Turbo" if m==FAMILIES[0] else m,".safetensors",optional=True)
            if any(self.vars["test:"+m].get()!=LATER for m in selected):
                v=self.var("comfy","Install ComfyUI for Studio")
                box=ttk.Combobox(self.body,textvariable=v,state="readonly",values=["Install ComfyUI for Studio","Use an existing ComfyUI folder"])
                box.pack(fill="x",pady=8)
                box.bind("<<ComboboxSelected>>",lambda e:self.render())
                if v.get().startswith("Use"):
                    self.field("comfyFolder","ComfyUI folder containing main.py",folder=True)
                    self.field("comfyPython","Python interpreter for ComfyUI")
        elif page=="Shortcuts":
            self.toggle("menu","Create an application menu launcher","True")
            self.toggle("desktop","Create a desktop shortcut")
        elif page=="Review":
            self.note(self.vars["folder"].get())
            for m in self.models(FAMILIES)+self.models(VISION)+["test:"+x for x in self.models(FAMILIES)]:
                mode=self.vars[m].get()
                self.note(m+" — "+mode)
                if mode in (URL,LOCAL):
                    self.note(self.vars[m+mode].get())
                    if m in VISION:self.note(self.vars[m+mode+" projector"].get())
            if any(self.vars["test:"+m].get()!=LATER for m in self.models(FAMILIES)):
                self.note(self.vars["comfy"].get())
                if self.vars["comfy"].get().startswith("Use"):
                    self.note(self.vars["comfyFolder"].get()+" · "+self.vars["comfyPython"].get())
            for key,label in (("menu","Application menu"),("desktop","Desktop shortcut")):
                self.note(label+" — "+("Yes" if self.vars[key].get()=="True" else "No"))

    def previous(self):
        self.index-=1
        self.render()

    def close(self):
        if not self.busy:self.win.destroy()

    def advance(self):
        try:
            if self.launcher:
                subprocess.Popen(["bash",str(self.launcher)],start_new_session=True)
                self.close()
                return
            if self.index==1:destination(self.vars["folder"].get())
            for key,suffix,remote in self.inputs:
                value=self.vars[key].get()
                if remote:
                    u=urlsplit(value)
                    if u.scheme!="https" or u.netloc!="huggingface.co" or "/resolve/" not in u.path or not u.path.lower().endswith(suffix) or u.query or u.fragment:
                        raise ValueError("Choose a direct Hugging Face /resolve/ link ending in "+suffix)
                elif not Path(value).is_file() or Path(value).suffix.lower()!=suffix:
                    raise ValueError("Choose an existing "+suffix+" file.")
            if self.index==4 and any(self.vars["test:"+m].get()!=LATER for m in self.models(FAMILIES)) and self.vars["comfy"].get().startswith("Use"):
                src=Path(self.vars["comfyFolder"].get())
                py=Path(self.vars["comfyPython"].get())
                if src.name!="ComfyUI" or not (src/"main.py").is_file() or not py.is_file() or not os.access(py,os.X_OK):
                    raise ValueError("Choose the ComfyUI directory containing main.py and its executable Python interpreter.")
            if self.index<len(self.pages)-1:
                self.index+=1
                self.render()
                return
            plan={k:v.get() for k,v in self.vars.items()}
            self.busy=True
            for b in (self.back,self.next,self.cancel):b.configure(state="disabled")
            for w in self.body.winfo_children():w.destroy()
            self.title.configure(text="Installing Studio")
            def worker():
                try:
                    launcher=install(self.archive,plan,lambda msg:self.events.put(("status",msg)))
                    self.events.put(("done",launcher))
                except Exception as exc:self.events.put(("error",str(exc)))
            threading.Thread(target=worker,daemon=True).start()
            self.poll()
        except (OSError,ValueError) as exc:messagebox.showerror("Check your selection",str(exc),parent=self.win)

    def poll(self):
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=="status":self.note(value)
            else:
                self.busy=False
                self.next.configure(state="normal")
                self.cancel.configure(state="normal")
                if kind=="error":
                    self.render()
                    messagebox.showerror("Installation interrupted",value,parent=self.win)
                else:
                    self.launcher=value
                    self.title.configure(text="Studio is ready")
                    self.next.configure(text="Open Studio")
                    self.cancel.configure(text="Close")
        if self.busy:self.win.after(200,self.poll)


if __name__=="__main__":
    window=tk.Tk()
    Wizard(window,Path(sys.argv[1]))
    window.mainloop()
