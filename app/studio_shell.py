"""Navegação e apresentação compartilhadas. Os comandos pertencem ao aplicativo."""
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from configuracao import ROOT,DATA

log=logging.getLogger("hydra.studio")
if not log.handlers:
    folder=DATA/"logs";folder.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(folder/"interface.log",maxBytes=500000,backupCount=2,encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler);log.setLevel(logging.INFO)

class Assets:
    def __init__(self):self.cache={}
    def image(self,relative,size):
        key=(relative,size)
        if key not in self.cache:
            try:
                with Image.open(ROOT/"HydraTrainStudio_Assets"/relative) as im:
                    im.thumbnail((size,size),Image.Resampling.LANCZOS)
                    self.cache[key]=ImageTk.PhotoImage(im)
            except (OSError,ValueError):
                log.warning("Asset ausente: %s",relative);self.cache[key]=None
        return self.cache[key]
    def icon(self,name,size=24):
        return self.image(f"icons/24/light/{name}.png",size)

class StudioBook(ttk.Notebook):
    def __init__(self,app,host,sidebar):
        super().__init__(host,style="Studio.TNotebook")
        self.app=app;self.aliases={};self.buttons={};self.icons={};self.sidebar=sidebar
        self.pack(fill="both",expand=True)
        self.bind("<<NotebookTabChanged>>",self.changed,add="+")
    def select(self,tab_id=None):
        if tab_id is None:return super().select()
        return super().select(self.aliases.get(str(tab_id),tab_id))
    def changed(self,_=None):
        current=self.select()
        for target,button in self.buttons.items():
            active=target==current
            icon=self.icons[target];variant="purple" if active or self.app.theme.get()=="Claro" else "light"
            button.configure(style="NavActive.TButton" if active else "Nav.TButton",
                             image=self.app.assets.image(f"icons/24/{variant}/{icon}.png",24))
        log.info("Página %s",self.tab(current,"text"))
    def navigation(self):
        pages={self.tab(t,"text"):t for t in self.tabs()}
        for title,icon in (("Início","home"),("Mídias","images"),("Revisão","layers"),
                           ("Treino e testes","play"),("Mesclar LoRAs","merge"),("Configuração","settings"),("Aparência","palette")):
            if title=="Configuração":ttk.Frame(self.sidebar,style="Sidebar.TFrame").pack(fill="both",expand=True)
            target=pages[title]
            image=self.app.assets.icon(icon)
            b=ttk.Button(self.sidebar,text="Configurações" if title=="Configuração" else title,
                         image=image,compound="left",style="Nav.TButton",
                         command=lambda t=target:self.select(t) if getattr(self.app,"tree",None) else None)
            b.pack(fill="x",pady=4);self.buttons[target]=b;self.icons[target]=icon
        self.changed()

def native_shell(app):
    try:app.iconbitmap(str(ROOT/"HydraTrainStudio_Assets/app_icon/HydraTrainStudio.ico"))
    except tk.TclError:log.warning("Ícone de janela indisponível")
    main=ttk.Frame(app);main.pack(fill="both",expand=True)
    side=ttk.Frame(main,width=250,padding=(13,12),style="Sidebar.TFrame");side.pack(side="left",fill="y");side.pack_propagate(False)
    def compact(event):
        if event.widget is app:side.configure(width=220 if event.width<=1150 else 250)
    app.bind("<Configure>",compact,add="+")
    ttk.Separator(main,orient="vertical").pack(side="left",fill="y")
    content=ttk.Frame(main);content.pack(fill="both",expand=True)
    bar=ttk.Frame(content,height=52,padding=(22,4));bar.pack(fill="x");bar.pack_propagate(False);bar.fixed_layout=True
    ttk.Label(bar,text="Projeto",style="Secondary.TLabel").pack(side="left")
    app.project_label=tk.StringVar(value=app.startup_root.name)
    projects=DATA/"projetos"
    box=ttk.Combobox(bar,textvariable=app.project_label,width=48,state="readonly",
                     postcommand=lambda:box.configure(values=sorted(p.name for p in projects.iterdir() if p.is_dir()) if projects.exists() else ()))
    box.pack(side="left",padx=12)
    def switch(_):
        if not hasattr(app,"project"):
            app.project_label.set(app.startup_root.name);return
        name=app.project_label.get()
        app.project_label.set(app.project.root.name)
        if app.busy or name==app.project.root.name:return
        from dataset import Dataset
        app._save_edit();app.adopt(Dataset(projects/name))
    box.bind("<<ComboboxSelected>>",switch)
    ttk.Frame(bar).pack(side="left",expand=True,fill="x")
    for title,cmd in (("Abrir",app._change_workspace),("Salvar",app.save_project),("Novo",app._reset)):
        ttk.Button(bar,text=title,image=app.assets.icon({"Abrir":"folder","Salvar":"save","Novo":"plus"}[title],18),compound="left",command=lambda fn=cmd:fn() if hasattr(app,"tree") else None).pack(side="left",padx=2)
    log.info("Navegação criada")
    return StudioBook(app,content,side)

def startup_logging(app):
    if getattr(app,"_studio_logging_ready",False):return
    app._studio_logging_ready=True
    def error(kind,value,tb):
        log.error("Callback UI",exc_info=(kind,value,tb))
        if hasattr(app,"status"):app.status.set("Erro na interface. Veja dados/logs/interface.log.")
    app.report_callback_exception=error
    mapped=False
    def first(event):
        nonlocal mapped
        if event.widget is app and not mapped:
            mapped=True;log.info("Primeiro mapeamento %sx%s",app.winfo_width(),app.winfo_height())
    app.bind("<Map>",first,add="+")

def home(app):
    page=app.home_page
    hero=ttk.Frame(page,padding=(0,12));hero.pack()
    ttk.Label(hero,image=app.assets.image("branding/hydra_symbol_128.png",90)).grid(row=0,column=0,rowspan=2)
    ttk.Label(hero,image=app.assets.image("branding/hydra_wordmark.png",330)).grid(row=0,column=1,sticky="sw",padx=12)
    ttk.Label(hero,text="Coleta de mídias, revisão de datasets e treinamento de LoRAs",style="Secondary.TLabel").grid(row=1,column=1,sticky="nw",padx=12)
    cards=ttk.Frame(page);cards.pack(fill="x",pady=12)
    specs=[("Baixar mídias","Download de imagens e vídeos","download",app.media_tab),
           ("Revisar e captionar","Editar imagens e legendas","tag",app.tab_review),
           ("Treinar LoRA","Iniciar um treinamento","gpu",app.training_tab),
           ("Mesclar LoRAs","Combinar modelos e pesos","merge",app.merge_tab),
           ("Ver datasets","Consultar o dataset atual","dataset",app.tab_review)]
    tiles=[]
    for label,desc,icon,target in specs:
        tile=ttk.Frame(cards,padding=12,style="Tile.TFrame",takefocus=True)
        def activate(event=None,t=target):
            if hasattr(app,"tree"):app.tabs.select(t)
        for child in (ttk.Label(tile,image=app.assets.image(f"icons/48/purple/{icon}.png",36),style="Tile.TLabel"),
                      ttk.Label(tile,text=label,style="TileTitle.TLabel"),
                      ttk.Label(tile,text=desc,wraplength=140,justify="center",style="Tile.TLabel")):
            child.pack(pady=3);child.bind("<Button-1>",activate)
        tile.bind("<Button-1>",activate);tile.bind("<Return>",activate);tile.bind("<space>",activate)
        def highlight(on,tile=tile):
            tile.configure(style="Hover.Tile.TFrame" if on else "Tile.TFrame")
            for child in tile.winfo_children():
                style=str(child.cget("style")).removeprefix("Hover.")
                child.configure(style=("Hover." if on else "")+style)
        for part in (tile,*tile.winfo_children()):
            part.bind("<Enter>",lambda _,fn=highlight:fn(True))
            part.bind("<Leave>",lambda _,fn=highlight:fn(False))
        tile.bind("<FocusIn>",lambda _,fn=highlight:fn(True))
        tile.bind("<FocusOut>",lambda _,fn=highlight:fn(False))
        tile.configure(cursor="hand2");tiles.append(tile)
    def reflow(width):
        cols=5 if width>=1020 else 3
        for col in range(5):cards.columnconfigure(col,weight=int(col<cols),uniform="tiles" if col<cols else "")
        for i,tile in enumerate(tiles):tile.grid(row=i//cols,column=i%cols,sticky="nsew",padx=4,pady=4,ipady=5)
    reflow(1120)
    cards.bind("<Configure>",lambda e:reflow(e.width))
    card=ttk.LabelFrame(page,text="Status do projeto",padding=16);card.pack(fill="x",pady=8)
    app.metrics=[]
    for i,(label,icon) in enumerate((("Imagens","images"),("Vídeos","film"),("Frames","layers"),("Com tags","tag"),("Com caption","caption"))):
        card.columnconfigure(i,weight=1,uniform="metric")
        box=ttk.Frame(card);box.grid(row=0,column=i,sticky="ew")
        ttk.Label(box,text=label,image=app.assets.icon(icon,18),compound="left").pack()
        var=tk.StringVar(value="0");app.metrics.append(var)
        ttk.Label(box,textvariable=var,style="Metric.TLabel").pack()
    lower=ttk.Frame(page);lower.pack(fill="x",pady=10)
    lower.columnconfigure((0,1),weight=1,uniform="lower")
    summary=ttk.LabelFrame(lower,text="Projeto atual",padding=16);summary.grid(row=0,column=0,sticky="nsew",padx=(0,8))
    app.home_summary=tk.StringVar(value="Carregando projeto…")
    ttk.Label(summary,textvariable=app.home_summary,wraplength=390).pack(anchor="w")
    activity=ttk.LabelFrame(lower,text="Atividade atual",padding=16);activity.grid(row=0,column=1,sticky="nsew",padx=(8,0))
    ttk.Label(activity,textvariable=app.status,wraplength=360).pack(anchor="w")
    row=ttk.Frame(page);row.pack(fill="x",pady=4)
    for label,cmd in (("Novo projeto",app._reset),("Abrir projeto",app._change_workspace),("Backup",app.backup),("Índice entre projetos",app.choose_library),("Ver LoRAs",app.open_loras)):
        ttk.Button(row,text=label,command=lambda fn=cmd:fn() if hasattr(app,"tree") else None).pack(side="left",padx=3)
    log.info("Página inicial montada com grade inicial explícita")
