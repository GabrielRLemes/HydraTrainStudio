import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from pathlib import Path
from ambiente import PROFILES,LORAS
from responsive import wrap_rows
from studio_shell import Assets,native_shell,home,startup_logging
from preferencias import Preferences,apply_style
from configuracao import read_json

def page(book,title):
    host=ttk.Frame(book,padding=4);book.add(host,text=title)
    if hasattr(book,"aliases"):
        inner=scrolling(host,padding=(22,16))
        if title!="Início":
            titles={"Revisão":"Revisão do dataset","Configuração":"Configurações"}
            icons={"Mídias":"images","Revisão":"layers","Treino e testes":"gpu","Mesclar LoRAs":"merge","Configuração":"settings","Aparência":"palette"}
            ttk.Label(inner,text="  "+titles.get(title,title),image=book.app.assets.icon(icons[title]),compound="left",style="PageTitle.TLabel").pack(anchor="w",pady=(0,4))
            subtitles={"Mídias":"Baixe, importe e extraia imagens e frames","Revisão":"Confira o recorte, as tags e a descrição das imagens.",
                       "Treino e testes":"Configure o treinamento e compare checkpoints.","Mesclar LoRAs":"Combine modelos compatíveis em um novo arquivo.",
                       "Configuração":"Projeto, hardware, serviços de IA e fontes de mídia.","Aparência":"Tema e tamanho de fonte do aplicativo."}
            ttk.Label(inner,text=subtitles[title],style="Secondary.TLabel").pack(anchor="w",pady=(0,10))
        book.aliases[str(inner)]=str(host)
        return inner
    return host

def scrolling(host,max_width=None,padding=8):
    canvas=tk.Canvas(host,highlightthickness=0)
    bar=ttk.Scrollbar(host,command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right",fill="y");canvas.pack(fill="both",expand=True)
    body=ttk.Frame(canvas,padding=padding)
    ident=canvas.create_window(0,0,anchor="nw",window=body)
    def fit(_=None):
        width=max(1,canvas.winfo_width())
        canvas.itemconfigure(ident,width=min(width,max_width) if max_width else width,
                             height=max(canvas.winfo_height(),body.winfo_reqheight()))
        canvas.configure(scrollregion=canvas.bbox("all"))
    body.bind("<Configure>",fit)
    body.bind("<Map>",lambda _:body.after_idle(fit),add="+")
    canvas.bind("<Configure>",fit)
    body.scroll_canvas=canvas
    root=host.winfo_toplevel()
    if not getattr(root,"page_wheel_bound",False):
        def wheel(event):
            widget=event.widget
            if isinstance(widget,(tk.Text,ttk.Treeview,ttk.Combobox)):return
            step=-int(event.delta/120)
            while isinstance(widget,tk.Misc):
                target=getattr(widget,"scroll_canvas",None)
                if target is not None:
                    top,bottom=target.yview()
                    if (step<0 and top>0) or (step>0 and bottom<1):
                        target.yview_scroll(step,"units");return "break"
                widget=widget.master
        root.bind_all("<MouseWheel>",wheel,add="+")
        root.page_wheel_bound=True
    return body

class Pipeline(Preferences):
    def shell_chrome(self):
        self.init_preferences()
        self.assets=Assets()
        head=ttk.Frame(self,height=64,padding=(16,6),style="Header.TFrame");head.pack(fill="x");head.pack_propagate(False);head.fixed_layout=True
        ttk.Label(head,image=self.assets.image("branding/hydra_symbol_128.png",44),style="Header.TLabel").pack(side="left")
        ttk.Label(head,image=self.assets.image("branding/hydra_wordmark.png",200),style="Header.TLabel").pack(side="left",padx=8)

        ttk.Button(head,text="Parar tarefa",command=lambda:self._cancel() if hasattr(self,"stop") else None).pack(side="right")
        foot=ttk.Frame(self,height=32,padding=(10,2));foot.pack(side="bottom",fill="x");foot.pack_propagate(False);foot.fixed_layout=True
        self.workspace_text=tk.StringVar(value=str(self.startup_root))
        self.hardware_short=tk.StringVar()
        for var,side in ((self.hardware_short,"right"),(self.workspace_text,"right"),(self.status,"left")):
            ttk.Label(foot,textvariable=var,width=1,anchor="w").pack(side=side,fill="x",expand=True,padx=4)
        self.tabs=native_shell(self)
        self.home_page=page(self.tabs,"Início")
        startup_logging(self)
        self.tab_env=page(self.tabs,"Configuração")
        self.media_tab=page(self.tabs,"Mídias")
        self.tab_review=page(self.tabs,"Revisão")
        self.training_tab=page(self.tabs,"Treino e testes")
        self.merge_tab=page(self.tabs,"Mesclar LoRAs")
        self.general_tab=page(self.tabs,"Aparência")
        home(self);self.tabs.navigation()
        self.tabs.select(self.home_page)
        apply_style(self)
    def shell(self):
        self.options_book=ttk.Notebook(self.tab_env);self.options_book.pack(fill="both",expand=True)
        self.tab_project=scrolling(page(self.options_book,"Projeto e preset"),860)
        self.tab_ai=scrolling(page(self.options_book,"IA e prompts"),860)
        self.accounts=scrolling(page(self.options_book,"Fontes e contas"),860)
        self.extract_settings=scrolling(page(self.options_book,"Extrator"),860)
        self.component_panel=scrolling(page(self.options_book,"Componentes"),860)
        self.media_book=ttk.Notebook(self.media_tab);self.media_book.pack(fill="both",expand=True)
        self.tab_search=scrolling(page(self.media_book,"Download"))
        frames_page=page(self.media_book,"Extrair frames")
        self.tab_frames=scrolling(frames_page)
        self.tab_import=scrolling(page(self.media_book,"Importar local"))
        ttk.Button(self.extract_settings,text="Opções e extração de frames",command=lambda:(self.tabs.select(self.media_tab),self.media_book.select(frames_page))).pack(anchor="w",padx=16,pady=16)
        self.train_book=ttk.Notebook(self.training_tab);self.train_book.pack(fill="both",expand=True)
        self.tab_train=page(self.train_book,"Treinar");self.tab_gallery=page(self.train_book,"Testar e comparar")
        meters=ttk.Frame(self.tab_review);meters.pack(fill="x",pady=(2,5))
        self.meters={}
        for col,(key,title) in enumerate([("work","Tarefa"),("download","Download"),("extract","Frames"),("tags","Tags"),("caption","Caption")]):
            meters.columnconfigure(col,weight=1,uniform="p")
            box=ttk.Frame(meters,padding=2);box.grid(row=0,column=col,sticky="ew")
            lab=ttk.Label(box,text=title,width=5);lab.pack(fill="x")
            bar=ttk.Progressbar(box,maximum=100);bar.pack(fill="x")
            self.meters[key]=(lab,bar)
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
        language_control(self,body)
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
        root=self.merge_tab
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
        config=ttk.LabelFrame(root,text="Configuração da mesclagem",padding=14);config.pack(fill="x",pady=8)
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
        if len(ids)==2:
            for i,key in enumerate(ids):
                weight,path=self.merge_table.item(key,"values")
                box=ttk.LabelFrame(self.pair,text=("Modelo A","Modelo B")[i],padding=12)
                self.pair.columnconfigure(i,weight=1,uniform="model")
                box.grid(row=0,column=i,sticky="nsew",padx=4)
                ttk.Label(box,text=Path(path).name,wraplength=280).pack(anchor="w")
                ttk.Label(box,text=f"Peso   {weight}").pack(anchor="w")
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


