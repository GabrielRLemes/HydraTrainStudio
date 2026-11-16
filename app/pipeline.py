import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from pathlib import Path
from ambiente import PROFILES,LORAS
from responsive import wrap_rows
from layout_ui import scrolling, pane, split, banner
from studio_shell import Assets,native_shell,home,startup_logging
from preferencias import Preferences,apply_style
from configuracao import read_json

def page(book,title):
    host=ttk.Frame(book,padding=4);book.add(host,text=title)
    if hasattr(book,"aliases"):
        inner=ttk.Frame(host,padding=(7,4))
        inner.pack(fill="both",expand=True)
        book.aliases[str(inner)]=str(host)
        return inner
    return host

class Pipeline(Preferences):
    def shell_chrome(self):
        self.init_preferences()
        self.assets=Assets()
        banner(self)
        foot=ttk.Frame(self,padding=(10,3))
        foot.pack(side="bottom",fill="x")
        ttk.Separator(foot).pack(fill="x",pady=(0,2))
        meters=ttk.Frame(foot)
        meters.pack(fill="x")
        self.meters={}
        for col,(key,title) in enumerate([("work","Tarefa"),("download","Download"),("extract","Frames"),("tags","Tags"),("caption","Caption")]):
            meters.columnconfigure(col,weight=1,uniform="p")
            box=ttk.Frame(meters,padding=2);box.grid(row=0,column=col,sticky="ew")
            lab=ttk.Label(box,text=title,width=5);lab.pack(fill="x")
            bar=ttk.Progressbar(box,maximum=100);bar.pack(fill="x")
            self.meters[key]=(lab,bar)
        def layout_meters(event):
            cols=5 if event.width>=max(890,self.font_size.get()*77) else 3
            if getattr(meters,"columns",0)==cols:return
            meters.columns=cols
            for col in range(5):meters.columnconfigure(col,weight=int(col<cols),uniform="p" if col<cols else "")
            for i,(label,_) in enumerate(self.meters.values()):
                label.master.grid(row=i//cols,column=i%cols,sticky="ew")
        meters.bind("<Configure>",layout_meters)
        statusbar=ttk.Frame(foot)
        statusbar.pack(fill="x")
        self.workspace_text=tk.StringVar(value=str(self.startup_root))
        self.hardware_short=tk.StringVar()
        statusbar.columnconfigure(0,weight=2)
        statusbar.columnconfigure(1,weight=1)
        for i,var in enumerate((self.status,self.workspace_text,self.hardware_short)):
            ttk.Label(statusbar,textvariable=var,width=1 if i<2 else None).grid(row=0,column=i,sticky="ew",padx=4)
        ttk.Button(statusbar,text="Parar tarefa",command=lambda:self._cancel() if hasattr(self,"stop") else None,
                   padding=(7,2)).grid(row=0,column=3)
        self.tabs=native_shell(self)
        self.home_page=page(self.tabs,"Início")
        startup_logging(self)
        self.tab_env=page(self.tabs,"Configuração")
        self.media_tab=page(self.tabs,"Mídias")
        self.tab_review=page(self.tabs,"Revisão")
        self.training_tab=page(self.tabs,"Treino e testes")
        self.merge_tab=page(self.tabs,"Mesclar LoRAs")
        home(self);self.tabs.navigation()
        self.tabs.select(self.home_page)
        apply_style(self)
    def shell(self):
        settings=split(self.tab_env)
        choices=scrolling(pane(settings,125,210,"never"),padding=4)
        self.options_book=ttk.Notebook(pane(settings,285,680),style="Studio.TNotebook")
        self.options_book.pack(fill="both",expand=True)
        self.tab_project=scrolling(page(self.options_book,"Projeto e preset"),860)
        self.tab_ai=scrolling(page(self.options_book,"IA e prompts"),860)
        self.accounts=scrolling(page(self.options_book,"Fontes e contas"),860)
        self.extract_settings=scrolling(page(self.options_book,"Extrator"),860)
        self.component_panel=scrolling(page(self.options_book,"Componentes"),860)
        self.general_tab=scrolling(page(self.options_book,"Aparência"))
        for tab in self.options_book.tabs():
            title=self.options_book.tab(tab,"text")
            ttk.Button(choices,text=title,command=lambda t=tab:self.options_book.select(t)).pack(fill="x",pady=2)
        def highlight(_=None):
            for tab,button in zip(self.options_book.tabs(),choices.pack_slaves()):
                button.configure(style="NavActive.TButton" if tab==self.options_book.select() else "Nav.TButton")
        self.options_book.bind("<<NotebookTabChanged>>",highlight)
        highlight()
        self.media_book=ttk.Notebook(self.media_tab);self.media_book.pack(fill="both",expand=True)
        search=split(page(self.media_book,"Download"))
        self.tab_search=scrolling(pane(search,235,500))
        self.search_results=scrolling(pane(search,165,450))
        frames_page=page(self.media_book,"Extrair frames")
        frames=split(frames_page)
        self.tab_frames=scrolling(pane(frames,250,460))
        self.frame_results=scrolling(pane(frames,200,450))
        imports=split(page(self.media_book,"Importar local"),"vertical")
        self.tab_import=scrolling(pane(imports,95,195))
        self.import_results=scrolling(pane(imports,75,220))
        ttk.Button(self.extract_settings,text="Opções e extração de frames",command=lambda:(self.tabs.select(self.media_tab),self.media_book.select(frames_page))).pack(anchor="w",padx=16,pady=16)
        self.train_book=ttk.Notebook(self.training_tab);self.train_book.pack(fill="both",expand=True)
        self.tab_train=page(self.train_book,"Treinar");self.tab_gallery=page(self.train_book,"Testar e comparar")
        for panel in (self.tab_search,self.tab_import,self.tab_frames):
            ttk.Label(panel,textvariable=self.status,style="Secondary.TLabel",wraplength=700).pack(side="bottom",fill="x",pady=4)
        self._search_ui();self._import_ui();self._review_ui();self._export_ui();self.studio_controls()
    def finish_layout(self):
        self.merge_layout()
        body=ttk.LabelFrame(self.general_tab,text="Preferências da interface",padding=16);body.pack(anchor="nw")
        for title,var,choices in (("Tema",self.theme,("Claro","Escuro")),("Tamanho da fonte",self.font_size,(9,10,11,12,14,16))):
            row=self.row(body)
            ttk.Label(row,text=title,width=18).pack(side="left")
            box=ttk.Combobox(row,textvariable=var,values=choices,state="readonly",width=14);box.pack(side="left")
            box.bind("<<ComboboxSelected>>",lambda _:apply_style(self))
        from idioma import language_control
        language_control(self,self.language_host)
        self.watch_preferences();self.load_prompts();apply_style(self)
        wrap_rows(self)
        self.after_import=[]
    def save_project(self):
        if self.busy:return
        try:
            self._save_edit();self.sync_options();self.project.save();self.save_preferences()
        except (OSError,ValueError) as exc:
            messagebox.showerror("Salvar projeto",str(exc));return
        self.status.set("Projeto salvo · "+self.project.root.name)
    def download_with_files(self):
        if self.busy:return
        files=filedialog.askopenfilenames(title="Arquivos locais a importar junto com o download")
        if not files:return
        self._download()
        if self.busy:self.after_import=[Path(p) for p in files]
    def complete_media(self,success):
        queued=getattr(self,"after_import",[])
        self.after_import=[]
        if success and queued:self.after_idle(lambda:self._import_paths(queued))
    def move_to_tests(self,run):
        self.gallery_ui.set_run(run)
        self.tabs.select(self.training_tab);self.train_book.select(self.tab_gallery)
    def batch_remove(self):
        if self.busy:return
        keys=list(self.tree.selection())
        if not keys:return
        if not messagebox.askyesno("Revisão",f"Remover {len(keys)} item(ns) da seleção de treino? Os arquivos originais serão preservados."):return
        self._save_edit()
        for key in keys:
            it=self.project.items[key]
            it.update(status="rejeitado",removed=True)
        self.project.save()
        self.current_key=None;self.current_image=None
        self._set_text(self.tags_text,"");self._set_text(self.cap_text,"")
        self._refresh_tree();self.refresh_gallery();self._draw()
        self.info.set("Selecione uma imagem para revisar.")
        remaining=self.tree.get_children()
        if remaining:self.tree.selection_set(remaining[0]);self._select()
    def merge_layout(self):
        work=split(self.merge_tab)
        root=scrolling(pane(work,240,570))
        output=scrolling(pane(work,240,430))
        entries=ttk.LabelFrame(root,text="LoRAs selecionados",padding=14);entries.pack(fill="x",pady=6)
        self.merge_empty=ttk.Label(entries,text="Adicione dois ou mais LoRAs da mesma base.",image=self.assets.image("ui/empty_loras.png",82),compound="top")
        self.merge_empty.pack(fill="x",pady=6)
        self.merge_table=ttk.Treeview(entries,columns=("peso","arquivo"),show="headings",height=4,selectmode="browse",displaycolumns=("arquivo","peso"))
        self.merge_table.heading("peso",text="Peso");self.merge_table.heading("arquivo",text="Arquivo")
        self.merge_table.column("peso",width=75,stretch=False);self.merge_table.pack(fill="x")
        row=self.row(entries)
        ttk.Button(row,text="Adicionar LoRAs…",command=self.merge_add).pack(side="left")
        ttk.Button(row,text="Alterar peso",command=self.merge_weight).pack(side="left",padx=3)
        def remove():
            self.merge_table.delete(*self.merge_table.selection());self.merge_refresh()
        ttk.Button(row,text="Remover da lista",command=remove).pack(side="left")
        self.merge_table.bind("<Double-1>",lambda _:self.merge_weight())
        self.pair=ttk.Frame(root);self.pair.pack(fill="x")
        config=ttk.LabelFrame(output,text="Configuração da mesclagem",padding=14);config.pack(fill="x",pady=8)
        row=self.row(config)
        self.merge_family=tk.StringVar(value=self.family.get());self.merge_name=tk.StringVar(value="Meu-LoRA-mesclado")
        ttk.Label(row,text="Família").pack(side="left")
        ttk.Combobox(row,textvariable=self.merge_family,values=PROFILES,state="readonly",width=15).pack(side="left",padx=6)
        ttk.Label(row,text="Nome de saída").pack(side="left")
        ttk.Entry(row,textvariable=self.merge_name).pack(side="left",fill="x",expand=True,padx=6)
        self.merge_status=tk.StringVar(value="Peso 1 aplica a contribuição inteira.")
        ttk.Label(config,textvariable=self.merge_status,wraplength=620).pack(anchor="w",pady=8)
        self.merge_dest=tk.StringVar()
        self.merge_family.trace_add("write",lambda *_:self.merge_dest.set(str(LORAS/self.merge_family.get())))
        self.merge_dest.set(str(LORAS/self.merge_family.get()))
        ttk.Label(config,textvariable=self.merge_dest).pack(anchor="w")
        self.merge_cta=ttk.Button(config,text="Mesclar e salvar",command=self.merge_start,style="Primary.TButton",state="disabled");self.merge_cta.pack(anchor="e")
    def merge_refresh(self):
        ids=self.merge_table.get_children()
        self.merge_cta.configure(state="normal" if len(ids)>=2 else "disabled")
        if ids:self.merge_empty.pack_forget()
        else:self.merge_empty.pack(fill="x",before=self.merge_table)
        for child in self.pair.winfo_children():child.destroy()
        if ids:
            for i,key in enumerate(ids):
                weight,path=self.merge_table.item(key,"values")
                box=ttk.LabelFrame(self.pair,text=("Modelo A","Modelo B")[i] if i<2 else f"LoRA {i+1}",padding=12)
                box.pack(fill="x",pady=3)
                photo=None
                gallery=getattr(self,"gallery_ui",None)
                from comparar import load_grade
                manifest=load_grade(gallery.dest) if gallery and gallery.dest else {}
                if manifest and not manifest.get("ranking"):
                    for idx,version in enumerate(manifest.get("versoes",[])):
                        if (LORAS/version["arquivo"]).resolve()!=Path(path).resolve():continue
                        sample=manifest.get("imagens",{}).get(f"{idx}-0")
                        if sample:photo=self.assets.image(gallery.dest/sample,100)
                        break
                if photo is None:photo=self.assets.image("ui/empty_loras.png",58)
                ttk.Label(box,image=photo).pack(side="left",padx=(0,4))
                icon=self.assets.image("icons/32/"+("purple" if i%2==0 else "cyan")+"/weights.png",24)
                ttk.Label(box,image=icon).pack(side="left",padx=(0,7))
                ttk.Label(box,text=Path(path).name,wraplength=280).pack(anchor="w")
                value=tk.StringVar(value=str(weight))
                ttk.Label(box,textvariable=value).pack(side="right")
                def adjust(v,k=key,label=value):
                    weight=round(float(v),2)
                    self.merge_table.set(k,"peso",str(weight))
                    label.set(str(weight))
                control=ttk.Scale(box,from_=min(0,float(weight)),to=max(2,float(weight)),orient="horizontal")
                control.set(float(weight))
                control.configure(command=adjust)
                control.pack(fill="x",expand=True,padx=5)
    def merge_add(self):
        paths=filedialog.askopenfilenames(initialdir=LORAS/self.merge_family.get(),filetypes=[("LoRA","*.safetensors")])
        existing={str(self.merge_table.set(i,"arquivo")).casefold() for i in self.merge_table.get_children()}
        for p in paths:
            f=str(Path(p).resolve())
            if f.casefold() not in existing:self.merge_table.insert("","end",values=("1",f));existing.add(f.casefold())
        self.merge_refresh()
    def merge_weight(self):
        sel=self.merge_table.selection()
        if not sel:return
        value=simpledialog.askfloat("Contribuição","Peso deste LoRA",initialvalue=float(self.merge_table.set(sel[0],"peso")))
        if value is not None:self.merge_table.set(sel[0],"peso",str(value))
        self.merge_refresh()
    def merge_start(self):
        if self.busy:return
        rows=[self.merge_table.item(i,"values") for i in self.merge_table.get_children()]
        if len(rows)<2:messagebox.showinfo("Mescla","Selecione pelo menos dois LoRAs.");return
        family=self.merge_family.get()
        args=[family,self.merge_name.get()]
        from uuid import uuid4
        runid=uuid4().hex
        args.extend(["--id",runid])
        for weight,path in rows:args.extend(["--entrada",path,weight])
        def done():
            runs=[p for p in (LORAS/family).glob(f"*-{runid}/treino.json")]
            if not runs:raise RuntimeError("Arquivo mesclado não encontrado.")
            self.merge_status.set("Salvo em "+str(runs[0].parent));self.move_to_tests(runs[0].parent)
        self.execute("Mesclando LoRAs","mesclar.py",args,done)


