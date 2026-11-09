from pathlib import Path
from tkinter import ttk
from configuracao import DATA,read_json,write_json

LANGUAGES=("Português","English","Español","简体中文")
FILE=DATA/"idioma.json"
ROWS=[line.split("|") for line in Path(__file__).with_name("idiomas.txt").read_text("utf-8-sig").splitlines() if line]
TABLE={row[0]:row for row in ROWS}

def language_control(app,body):
    saved=read_json(FILE,{}).get("idioma",LANGUAGES[0])
    row=app.row(body)
    ttk.Label(row,text="Idioma",width=18).pack(side="left")
    box=ttk.Combobox(row,state="readonly",values=LANGUAGES,width=14)
    box.set(saved if saved in LANGUAGES else LANGUAGES[0]);box.pack(side="left")
    def translate(widget):
        idx=LANGUAGES.index(box.get())
        def lookup(text):
            key=text.strip()
            if key in TABLE:return text.replace(key,TABLE[key][idx])
            return text
        if isinstance(widget,(ttk.Label,ttk.Button,ttk.Checkbutton,ttk.Radiobutton,ttk.LabelFrame)):
            if "textvariable" not in widget.keys() or not widget.cget("textvariable"):
                original=getattr(widget,"_source_label",str(widget.cget("text")))
                if original.strip() in TABLE:
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
    box.bind("<<ComboboxSelected>>",change)
    app.bind_all("<Map>",lambda event:translate(event.widget) if hasattr(event.widget,"tk") else None,add="+")
    walk(app)
