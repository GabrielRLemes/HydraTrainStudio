from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk
from configuracao import DATA,read_json,write_json

LANGUAGES=("Português","English","Español","简体中文")
FILE=DATA/"idioma.json"
ROWS=[line.split("|") for line in Path(__file__).with_name("idiomas.txt").read_text("utf-8-sig").splitlines() if line]
TABLE={row[0]:row for row in ROWS}

def language_control(app,body):
    saved=read_json(FILE,{}).get("idioma",LANGUAGES[0])
    row=app.row(body)
    ttk.Label(row,text="Idioma",width=8).pack(side="left")
    box=ttk.Combobox(row,state="readonly",values=LANGUAGES,width=14)
    box.set(saved if saved in LANGUAGES else LANGUAGES[0]);box.pack(side="left")
    patterns=[]
    for key,entries in TABLE.items():
        if "{0}" in key:
            regex="".join("(.+?)" if re.fullmatch(r"\{\d+\}",part) else re.escape(part)
                          for part in re.split(r"(\{\d+\})",key))
            patterns.append((re.compile(regex),entries))
    def lookup(text):
        idx=LANGUAGES.index(box.get())
        if idx==0:return text
        if text.strip() in TABLE:return text.replace(text.strip(),TABLE[text.strip()][idx])
        for regex,entries in patterns:
            match=regex.fullmatch(text)
            if match:return entries[idx].format(*match.groups())
        return text
    app.ui_text=lookup
    mirrors={}
    def display(name,value):
        if name=="compat":return " · ".join(lookup(v) for v in value.split(" · "))
        lines=value.split("\n")
        if name=="short_info" and "|" in value:
            prefix,sep,state=value.rpartition("|")
            return prefix+sep+" · ".join(lookup(v) for v in state.split(" · "))
        return "\n".join(line if name=="home_summary" and i==0 else lookup(line) for i,line in enumerate(lines))
    def mirror(name,var):
        if name not in mirrors:
            shown=tk.StringVar(master=app)
            def refresh(*_):shown.set(display(name,var.get()))
            mirrors[name]=(shown,refresh)
            var.trace_add("write",refresh);refresh()
        return mirrors[name][0]
    def translate(widget):
        if isinstance(widget,ttk.Combobox):
            if not hasattr(widget,"_localized_options"):
                keys=tuple(widget.cget("values"))
                binding=str(widget.cget("textvariable"))
                fields=[getattr(app,k,None) for k in ("theme","preset","sidecar")]
                fields.append(getattr(getattr(app,"gallery_ui",None),"mode",None))
                original=next((v for v in fields if v is not None and str(v)==binding),None)
                if original is not None and keys and all(k in TABLE for k in keys):
                    shown=tk.StringVar(master=app)
                    def sync(*_):
                        shown.set(lookup(original.get()))
                    def select(*_):
                        labels=tuple(lookup(k) for k in keys)
                        if shown.get() in labels:
                            key=keys[labels.index(shown.get())]
                            if original.get()!=key:original.set(key)
                    widget.configure(textvariable=shown)
                    widget._localized_options=(keys,shown,sync)
                    original.trace_add("write",sync);shown.trace_add("write",select)
            if hasattr(widget,"_localized_options"):
                keys,shown,sync=widget._localized_options
                widget.configure(values=[lookup(k) for k in keys]);sync()
        if isinstance(widget,(ttk.Label,ttk.Button)) and widget.cget("textvariable"):
            binding=str(widget.cget("textvariable"))
            for name in ("home_summary","summary","review_summary","status","hardware_short","selection_info","short_info","res_label","hw","compat","merge_status"):
                var=getattr(app,name,None)
                if var is not None and binding==str(var):
                    widget.configure(textvariable=mirror(name,var));break
        if isinstance(widget,(ttk.Label,ttk.Button,ttk.Checkbutton,ttk.Radiobutton,ttk.LabelFrame)):
            if "textvariable" not in widget.keys() or not widget.cget("textvariable"):
                original=getattr(widget,"_source_label",str(widget.cget("text")))
                if original.strip() in TABLE or lookup(original)!=original:
                    widget._source_label=original;widget.configure(text=lookup(original))
        if isinstance(widget,ttk.Notebook):
            if not hasattr(widget,"_source_tabs"):widget._source_tabs={t:widget.tab(t,"text") for t in widget.tabs()}
            for tab,title in widget._source_tabs.items():widget.tab(tab,text=lookup(title))
        if isinstance(widget,ttk.Treeview):
            for col in ("#0",*widget.cget("columns")):
                title=widget.heading(col,"text")
                if not hasattr(widget,"_source_headings"):widget._source_headings={}
                title=widget._source_headings.setdefault(col,title)
                widget.heading(col,text=lookup(title))
    def walk(widget):
        translate(widget)
        for child in widget.winfo_children():walk(child)
    def change(_):
        write_json(FILE,{"idioma":box.get()});walk(app)
        for _,refresh in mirrors.values():refresh()
        app.draw_progress()
    box.bind("<<ComboboxSelected>>",change)
    app.bind_all("<Map>",lambda event:translate(event.widget) if hasattr(event.widget,"tk") else None,add="+")
    walk(app)
