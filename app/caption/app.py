"""Caption Create 1.0 prototype: local-first LoRA dataset preparation GUI."""
from __future__ import annotations
import copy
import json
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from core import AIConfig, atomic_json
from captions import create_caption, create_tags, test_llama_vision
from caption_profiles import PROFILE_ORDER, PROFILE_CUSTOM, PROFILE_SDXL, PROFILE_DETAILED, PROFILE_DESCRIPTIONS, get_profile_prompt
from dataset import Dataset
from sources import SOURCES, SourceClient, build_query

from concurrent.futures import Future, ThreadPoolExecutor
from live import Progress
from studio import Studio
from sources import canonical_tags

VERSION = '1.2.1'
FONT = ('Segoe UI', 10)
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'dados' / 'projetos' / 'Principal'


class CaptionCreate(Studio, tk.Tk):
    def __init__(self, deferred=False):
        super().__init__()
        self.title('Caption Create ' + VERSION)
        self.geometry('1360x890')
        self.minsize(min(1100,self.winfo_screenwidth()-60), min(720,self.winfo_screenheight()-100))
        if deferred:
            self.title("HydraTrainStudio")
            self.geometry(f"{min(1440,self.winfo_screenwidth()-50)}x{min(900,self.winfo_screenheight()-95)}")
            self.startup_root=DEFAULT_ROOT
            self.busy=True
            self._variables();self._styles()
            self.shell_chrome()
            incoming=queue.Queue()
            def load():
                try:incoming.put((Dataset(DEFAULT_ROOT),None))
                except Exception as exc:incoming.put((None,exc))
            def collect():
                try:project,error=incoming.get_nowait()
                except queue.Empty:self.after(40,collect);return
                if error:
                    self.status.set("Falha ao carregar projeto: "+str(error))
                    return
                self._build_window(project)
                self._after_ready()
            threading.Thread(target=load,daemon=True).start()
            self.after(40,collect)
            return
        self._build_window(Dataset(DEFAULT_ROOT))

    def _build_window(self,project):
        self.project=project
        self.events = queue.Queue()
        self.thread = None
        self.stop = threading.Event()
        self.progress=Progress()
        self.editable_job=False
        self.busy = False
        self.current_key = None
        self.current_image = None
        self.current_photo = None
        self.current_dims = (1, 1)
        self.draw_bounds = None
        self.current_preview = {}
        self.profile_custom = ''
        if not hasattr(self,"tabs"):
            self._variables();self._styles()
        self._ui()
        self._refresh_tree()
        self.tree.bind("<Delete>",lambda event:self._reject())
        self.bind("<Control-s>",lambda event:self._shortcut(self._save_edit))
        self.bind("<Control-Return>",lambda event:self._shortcut(lambda:self.review_ai("caption",True)))
        self.after(130, self._poll)
        self.protocol('WM_DELETE_WINDOW', self._close)

    def _variables(self):
        self.query = tk.StringVar(value='gardevoir solo')
        self.excluded = tk.StringVar(value='')
        self.min_score = tk.StringVar(value='100')
        self.limit = tk.StringVar(value='25')
        self.site_vars = {s: tk.BooleanVar(value=s == 'e621') for s in SOURCES}
        self.username = tk.StringVar()
        self.gel_id = tk.StringVar()
        self.gel_key = tk.StringVar()
        self.rule_id = tk.StringVar()
        self.rule_key = tk.StringVar()
        self.derpi_key = tk.StringVar()
        self.provider = tk.StringVar(value='llama.cpp (local)')
        self.model = tk.StringVar(value='qwen3vl-8b-abliterated')
        self.api_url = tk.StringVar(value='http://127.0.0.1:8080')
        self.api_key = tk.StringVar()
        self.trigger = tk.StringVar(value='mystyle')
        self.profile = tk.StringVar(value=PROFILE_DETAILED)
        self.caption_mode = tk.StringVar(value='Ambos')
        self.resolution = tk.StringVar(value='768')
        self.fit_mode = tk.StringVar(value='Recortar 1:1')
        self.image_format = tk.StringVar(value='PNG')
        self.output = tk.StringVar(value=str(Path.home() / 'CaptionCreate_Export'))
        self.crop_scale = tk.DoubleVar(value=1.0)
        self.status = tk.StringVar(value="Carregando projeto…" if hasattr(self,"startup_root") else "Pronto")
        self.stats = tk.StringVar(value='')
        self.info = tk.StringVar(value='Selecione uma imagem para revisar.')
        self.prompt_hint = tk.StringVar(value='')
        self.import_recursive = tk.BooleanVar(value=False)
        self.follow_new = tk.BooleanVar(value=True)

    def _styles(self):
        self.configure(bg='#eef1f5')
        st = ttk.Style(self)
        if 'clam' in st.theme_names():
            st.theme_use('clam')
        st.configure('.', font=FONT)
        st.configure('TNotebook.Tab', padding=(18,9))
        st.configure('Primary.TButton', padding=(12,8), font=('Segoe UI',10,'bold'))
        st.configure('TLabelFrame', padding=(5,5))

    @staticmethod
    def row(parent, pady=4):
        r = ttk.Frame(parent)
        r.pack(fill='x', pady=pady)
        return r

    @staticmethod
    def field(parent, title, var, width=20, secret=False):
        r = ttk.Frame(parent)
        r.pack(fill='x', pady=3)
        ttk.Label(r, text=title, width=25, anchor='w').pack(side='left')
        entry = ttk.Entry(r, textvariable=var, width=width, show='•' if secret else '')
        entry.pack(side='left', fill='x', expand=True)
        return entry

    def _ui(self):
        head = ttk.Frame(self, padding=(15, 11))
        head.pack(fill='x')
        ttk.Label(head, text='HydraTrainer', font=('Segoe UI',19,'bold')).pack(side='left')
        ttk.Label(head, text='Treino local de LoRA', foreground='#667085').pack(side='left', padx=15)
        ttk.Button(head, text='Novo projeto', command=self._reset).pack(side='right', padx=5)
        ttk.Button(head, text='Trocar workspace', command=self._change_workspace).pack(side='right', padx=5)
        ttk.Button(head, text='Parar tarefa', command=self._cancel).pack(side='right', padx=5)
        panel=ttk.Frame(self,padding=(14,0,14,5))
        panel.pack(fill="x")
        self.meters={}
        for col,(key,title) in enumerate([("work","Trabalho"),("download","Download"),("extract","Extração"),("tags","Tags"),("caption","Descrições")]):
            panel.columnconfigure(col,weight=1,uniform="meter")
            box=ttk.Frame(panel,padding=(3,0))
            box.grid(row=0,column=col,sticky="ew")
            label=ttk.Label(box,text=title+" · aguardando",width=35)
            label.pack(fill="x")
            bar=ttk.Progressbar(box,maximum=100)
            bar.pack(fill="x")
            self.meters[key]=(label,bar)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=14, pady=(0,6))
        self.tab_search = ttk.Frame(self.tabs, padding=12)
        self.tab_import = ttk.Frame(self.tabs, padding=12)
        self.tab_review = ttk.Frame(self.tabs, padding=9)
        self.tab_export = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.tab_search, text='Buscar boorus')
        self.tabs.add(self.tab_import, text='Importar mídias')
        self.tabs.add(self.tab_review, text='Revisar e editar')
        self.tab_ai=ttk.Frame(self.tabs,padding=12)
        self.tabs.add(self.tab_ai,text='IA e captions')
        self.tabs.add(self.tab_export,text='Exportação')
        self._search_ui()
        self._import_ui()
        self._review_ui()
        self._export_ui()
        self.studio_controls()
        foot = ttk.Frame(self, padding=(14,5))
        foot.pack(fill='x')
        ttk.Label(foot, textvariable=self.status, foreground='#404e61').pack(side='left', fill='x', expand=True)
        ttk.Label(foot, textvariable=self.stats).pack(side='right')

    def _search_ui(self):
        root = self.tab_search
        frame = ttk.LabelFrame(root, text='Fontes de mídia (selecione uma ou várias)', padding=10)
        frame.pack(fill='x', pady=(0,9))
        r = self.row(frame)
        for s in SOURCES:
            ttk.Checkbutton(r, text=s, variable=self.site_vars[s]).pack(side='left', padx=(0,23))
        ttk.Label(frame, text='Rule34: conector experimental (pode exigir verificação de idade). A busca usa as APIs oficiais/documentadas.',
                  foreground='#687589').pack(anchor='w', pady=(3,0))
        f = ttk.LabelFrame(root, text='Busca', padding=12)
        f.pack(fill='x', pady=7)
        self.field(f, 'Tags obrigatórias:', self.query)
        self.field(f, 'Excluir tags (vírgula):', self.excluded)
        r = self.row(f)
        ttk.Label(r, text='Score mínimo e621:', width=25).pack(side='left')
        ttk.Entry(r, textvariable=self.min_score, width=9).pack(side='left')
        ttk.Label(r, text='Limite de novos arquivos por site:', padding=(20,0)).pack(side='left')
        ttk.Entry(r, textvariable=self.limit, width=10).pack(side='left')
        ttk.Label(f, text='Somente no e621 aplica-se score:>=100 por padrão. Os outros sites usam as próprias tags e filtros.',
                  foreground='#687589').pack(anchor='w')
        cred = ttk.LabelFrame(self.accounts,text="Contas dos sites",padding=10);cred.pack(fill="x")
        for title,var,secret in (
            ("Usuário e621",self.username,False),("API key e621",self.e621_key,True),
            ("Usuário Danbooru",self.dan_user,False),("API key Danbooru",self.dan_key,True),
            ("Gelbooru user ID",self.gel_id,False),("Gelbooru API key",self.gel_key,True),
            ("Rule34 user ID",self.rule_id,False),("Rule34 API key",self.rule_key,True),("Derpibooru API key",self.derpi_key,True)):
            self.field(cred,title,var,secret=secret)
        ttk.Label(cred,text="As contas e chaves são salvas para o usuário atual do Windows.").pack(anchor="w",pady=3)
        ttk.Button(cred,text="Redefinir credenciais…",command=self.reset_accounts).pack(anchor="w")
        self.count_all=tk.BooleanVar(value=False)
        ttk.Checkbutton(f,text="Contar todas as páginas quando o site não informar o total",variable=self.count_all).pack(anchor="w")
        act = ttk.Frame(root); act.pack(fill='x', pady=7)
        ttk.Button(act, text='Consultar resultados', command=self._search_preview).pack(side='left')
        ttk.Button(act, text='Baixar', command=self._download, style='Primary.TButton').pack(side='left', padx=10)
        ttk.Button(act,text="Baixar e importar arquivos…",command=self.download_with_files).pack(side="left")
        results=ttk.LabelFrame(root,text="Resultados da busca",padding=10);results.pack(fill="both",expand=True,pady=6)
        self.search_out = tk.Text(results,width=1,height=9, wrap='word', state='disabled', font=('Consolas',10))
        self.search_out.pack(fill='both', expand=True, pady=(10,0))

    def _import_ui(self):
        root = self.tab_import
        frame = ttk.LabelFrame(root, text='Importação de mídias locais', padding=18)
        frame.pack(fill='x', pady=(0,14))
        ttk.Label(frame, text='Adicione imagens já existentes ao projeto. O programa copia os arquivos para uma área de trabalho e nunca altera os originais.').pack(anchor='w', pady=5)
        r = self.row(frame)
        ttk.Button(r, text='Selecionar imagens, animações ou vídeos', command=self._import_files).pack(side='left')
        ttk.Button(r, text='Selecionar uma pasta', command=self._import_folder).pack(side='left', padx=12)
        ttk.Checkbutton(r, text='Incluir subpastas', variable=self.import_recursive).pack(side='left')
        self.import_out = tk.Text(root, height=3, state='disabled', font=('Consolas',10))
        self.import_out.pack(fill='both', expand=True, pady=14)

    def _review_ui(self):
        pane=ttk.Frame(self.tab_review);pane.pack(fill="both",expand=True)
        for i,w in enumerate((28,44,28)):pane.columnconfigure(i,weight=w,uniform="review")
        pane.rowconfigure(0,weight=1)
        left=ttk.LabelFrame(pane,text="Imagens",padding=8)
        right=ttk.LabelFrame(pane,text="Prévia",padding=8)
        summary=ttk.LabelFrame(pane,text="Resumo do dataset",padding=12)
        for i,block in enumerate((left,right,summary)):
            block.grid(row=0,column=i,sticky="nsew",padx=4)
        self.review_summary=tk.StringVar()
        ttk.Label(summary,textvariable=self.review_summary,justify="left",wraplength=220).pack(anchor="w",pady=(0,12))
        ttk.Label(left,text="Ctrl / Shift para selecionar").pack(anchor="w",pady=3)
        listbox=ttk.Frame(left);listbox.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(listbox,columns=("origin","state","tags","caption"),selectmode="extended")
        from responsive import Tiles
        self.tiles=Tiles(self,listbox,self.tree)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        actions = self.row(left, 8)
        ttk.Button(actions, text='Aprovar seleção', command=self.approve_selection).pack(side='left')
        ttk.Button(actions, text='Remover seleção', command=self._reject).pack(side='left', padx=6)
        ttk.Button(left, text='Próximo item pendente', command=self.next_pending).pack(fill='x')
        project_actions=ttk.LabelFrame(summary,text="Projeto inteiro",padding=4)
        project_actions.pack(fill="x",pady=4)
        for label,cmd in (("Refazer todas as captions",lambda:self.redo_project("caption")),
                          ("Refazer todas as tags",lambda:self.redo_project("tags")),
                          ("Aprovar tudo e treinar",self.approve_and_train)):
            ttk.Button(project_actions,text=label,command=cmd).pack(fill="x",pady=1)
        ttk.Label(right, textvariable=self.info, wraplength=430, font=('Segoe UI',10,'bold')).pack(anchor='w', pady=(0,6))
        self.canvas = tk.Canvas(right, bg='#11131E', width=1,height=265, highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _:self._draw())
        self.canvas.bind('<Button-1>', self._crop_click)
        self.canvas.bind('<B1-Motion>', self._crop_click)
        self.canvas.bind('<ButtonRelease-1>', self._crop_done)
        r = self.row(right,7)
        ttk.Label(r, text='Escala do recorte').pack(side='left')
        ttk.Scale(r, from_=0.25, to=1.0, variable=self.crop_scale, command=self._crop_scale_change).pack(side='left', fill='x', expand=True, padx=10)
        ttk.Button(r, text='Centralizar', command=self._crop_center).pack(side='left')
        editor=ttk.Notebook(right);editor.pack(fill="x",pady=5)
        a=ttk.Frame(editor);b=ttk.Frame(editor)
        editor.add(a,text="Tags (SDXL)");editor.add(b,text="Descrição (Krea2)")
        self.tags_text = tk.Text(a, width=1,height=7, wrap='word', undo=True, font=('Segoe UI',10))
        self.cap_text = tk.Text(b, width=1,height=7, wrap='word', undo=True, font=('Segoe UI',10))
        for text in (self.tags_text,self.cap_text):
            scroll=ttk.Scrollbar(text.master,command=text.yview);scroll.pack(side="right",fill="y")
            text.configure(yscrollcommand=scroll.set);text.pack(fill="both",expand=True)
        actions=ttk.LabelFrame(summary,text="Seleção atual",padding=6);actions.pack(fill="x",pady=8)
        for i,(label,cmd) in enumerate((("Salvar edição",self.save_selection_edit),("Gerar tags",lambda:self.review_ai("tags")),
                          ("Refazer tags",lambda:self.review_ai("tags",True)),("Gerar caption",lambda:self.review_ai("caption")),
                          ("Refazer caption",lambda:self.review_ai("caption",True)),("Melhorar caption",lambda:self.review_ai("enhance",True)))):
            actions.columnconfigure(i%2,weight=1,uniform="action")
            ttk.Button(actions,text=label,command=cmd,padding=(2,5)).grid(row=i//2,column=i%2,sticky="ew",padx=1,pady=2)
        def initial_item(_):
            keys=self.tree.get_children()
            if keys and not self.tree.selection():
                self.tree.selection_set(keys[0]);self.tree.focus(keys[0]);self._select()
        self.tab_review.bind("<Map>",initial_item,add="+")
        def copy():
            value=(self.tags_text if editor.index("current")==0 else self.cap_text).get("1.0","end-1c")
            self.clipboard_clear();self.clipboard_append(value)
        ttk.Button(actions,text="Copiar texto",command=copy,padding=(2,5)).grid(row=3,column=0,columnspan=2,sticky="ew",pady=2)
        def step(delta):
            keys=self.tree.get_children()
            if not keys:return
            index=keys.index(self.current_key) if self.current_key in keys else 0
            key=keys[min(max(index+delta,0),len(keys)-1)]
            self.tree.focus(key);self.tree.selection_set(key);self.tiles.see(key);self._select()
        arrows=ttk.Frame(left);arrows.pack(fill="x",pady=2)
        for i,(label,delta) in enumerate((("‹ Anterior",-1),("Próxima ›",1))):
            arrows.columnconfigure(i,weight=1,uniform="arrow")
            ttk.Button(arrows,text=label,command=lambda d=delta:step(d),padding=(2,4)).grid(row=0,column=i,sticky="ew")

        self.selection_info=tk.StringVar(value="Selecione itens para editar em lote.")
        ttk.Label(left,textvariable=self.selection_info,wraplength=200).pack(anchor="w")
        
    def _export_ui(self):
        root = self.tab_ai
        ai = ttk.LabelFrame(root, text='IA local e serviços externos', padding=10); ai.pack(fill='x', pady=(0,7))
        r = self.row(ai)
        ttk.Label(r, text='Provedor:', width=12).pack(side='left')
        providers = ['llama.cpp (local)', 'Ollama (local)', 'Google Gemini', 'OpenRouter', 'Nenhuma']
        provider_box=ttk.Combobox(r,state='readonly',values=providers,textvariable=self.provider,width=21);provider_box.pack(side='left');provider_box.bind('<<ComboboxSelected>>',self.provider_changed)
        ttk.Label(r, text='Modelo:', padding=(12,0)).pack(side='left')
        ttk.Entry(r, textvariable=self.model).pack(side='left', fill='x', expand=True)
        self.field(ai, 'Endereço local:', self.api_url)
        self.field(ai, 'API key externa:', self.api_key, secret=True)
        self.field(ai, 'Token de estilo:', self.trigger)
        r = self.row(ai)
        ttk.Button(r, text='Testar visão llama.cpp', command=self._test_llama).pack(side='left')
        ttk.Label(r, text='Pré-configurado: http://127.0.0.1:8080 · qwen3vl-8b-abliterated', foreground='#667085', padding=(15,0)).pack(side='left')
        ttk.Checkbutton(ai,text='Usar Think em todas as análises visuais: tags, captions e melhorias (llama.cpp local)',variable=self.vision_think).pack(anchor='w')
        profiles = ttk.LabelFrame(root, text='Legendas / prompts', padding=10); profiles.pack(fill='x', pady=(0,7))
        r = self.row(profiles)
        ttk.Label(r, text='Perfil de caption:', width=20).pack(side='left')
        p = ttk.Combobox(r, values=PROFILE_ORDER, textvariable=self.profile, state='readonly', width=32)
        self.prompt_box=p;p.pack(side="left");p.bind("<<ComboboxSelected>>",self.show_prompt)
        self.prompt=tk.Text(profiles,height=6,wrap="word",undo=True);self.prompt.pack(fill="x",pady=5)
        self.prompt.bind("<<Modified>>",self.edit_prompt)
        r=self.row(profiles)
        ttk.Button(r,text="Criar prompt…",command=self.named_prompt).pack(side="left")
        ttk.Button(r,text="Renomear…",command=lambda:self.named_prompt(True)).pack(side="left",padx=5)
        ttk.Button(r,text="Salvar configurações",command=self.save_preferences).pack(side="right")

    def _profile_changed(self, _=None):
        name = self.profile.get()
        if name == PROFILE_CUSTOM:
            text = self.profile_custom or get_profile_prompt(PROFILE_DETAILED)
        else:
            text = get_profile_prompt(name)
        self.prompt.delete('1.0','end'); self.prompt.insert('1.0', text)
        self.prompt_hint.set(PROFILE_DESCRIPTIONS.get(name, ''))

    def _save_custom_prompt(self):
        self.profile_custom = self.prompt.get('1.0','end-1c').strip()
        if not self.profile_custom:
            messagebox.showwarning('Prompt', 'Digite um prompt para salvar.')
            return
        self.profile.set(PROFILE_CUSTOM)
        (self.project.root/'prompt_personalizado.txt').write_text(self.profile_custom, encoding='utf-8')
        self.status.set('Prompt personalizado salvo para este projeto.')

    def _client(self):
        client=SourceClient(self.username.get(),self.gel_id.get(),self.gel_key.get(),
                            self.rule_id.get(),self.rule_key.get(),self.derpi_key.get(),self.stop)
        client.e621_key=self.e621_key.get()
        client.dan_auth=(self.dan_user.get(),self.dan_key.get()) if self.dan_user.get() and self.dan_key.get() else None
        return client

    def _selected_sites(self):
        sites = [s for s in SOURCES if self.site_vars[s].get()]
        if not sites:
            raise ValueError('Marque pelo menos uma fonte.')
        if 'e621' in sites and not self.username.get().strip():
            raise ValueError('Informe seu usuário e621 ou desmarque e621.')
        return sites

    def _search_preview(self):
        try:
            sources = self._selected_sites(); score = int(self.min_score.get())
            queries = {s:build_query(s, self.query.get(), self.excluded.get(), score) for s in sources}
        except Exception as exc:
            messagebox.showerror('Busca', str(exc)); return
        count_all=self.count_all.get()
        def task():
            client = self._client()
            lines = []
            self.progress.plan(len(queries))
            for source, query in queries.items():
                if self.stop.is_set(): break
                try:
                    result = client.search(source, query)
                    total = result.total
                    if source == 'e621':
                        try: total = client.count(source, query)
                        except Exception: pass
                    if total is None and not result.has_more:
                        total=len(result.posts)+result.skipped
                    if total is None and count_all:
                        seen={p.key for p in result.posts}
                        last=result;page_no=1;skipped=result.skipped
                        while last.has_more:
                            if self.stop.is_set():raise InterruptedError()
                            page_no+=1;last=client.search(source,query,page_no)
                            ids={p.key for p in last.posts}
                            if ids and ids<=seen:raise ValueError("O site repetiu a página; total indisponível.")
                            seen.update(ids);skipped+=last.skipped
                            self.events.put(("search_out","\\n".join(lines+[f"{source}: contando página {page_no} · {len(seen)} arquivos encontrados"])))
                        total=len(seen)+skipped
                    label = f'{total:,} resultados' if total is not None else f'{len(result.posts)} posts válidos na primeira página (total não informado)'
                    from collections import Counter
                    formats = Counter(p.media_type for p in result.posts)
                    lines.append(f"{source}: {label} | primeira página por metadados: {dict(formats)} · ignorados {result.skipped}")
                    lines.extend(f"  #{p.post_id} {p.media_type} {p.page_url}" for p in result.posts)
                except Exception as exc:
                    lines.append(f'{source}: ERRO — {str(exc)[:200]}')
                self.progress.advance()
                self.events.put(('search_out', '\n'.join(lines)))
        self._run('Consultando fontes', task)

    def _download(self):
        try:
            sources = self._selected_sites(); score = int(self.min_score.get()); cap = int(self.limit.get())
            if cap < 1 or cap > 2000: raise ValueError('Defina limite entre 1 e 2000 por site (proteção do protótipo).')
            queries = {s:build_query(s, self.query.get(), self.excluded.get(), score) for s in sources}
        except Exception as exc:
            messagebox.showerror('Busca', str(exc)); return
        if self.busy:return
        if not messagebox.askyesno("Uso do material","Confirma que tem autorização para baixar e usar a mídia desta busca?"):return
        try:self.sync_options()
        except Exception as e:messagebox.showerror("Extrator",str(e));return
        self.project.auto_extract = self.process_download.get()
        allowed = {k for k,v in self.media_filters.items() if v.get()}
        self.project.allowed_media=allowed
        if not allowed:messagebox.showerror("Busca","Selecione um tipo de mídia.");return
        try:after_media=self.prepare_callback(self.project.auto_extract and self.download_ai.get(),download=True)
        except ValueError as e:messagebox.showinfo("Busca",str(e));return
        self.tabs.select(self.tab_review)
        def task():
            client = self._client()
            self.progress.plan(cap*len(queries))
            summary = []
            for src, query in queries.items():
                done = duplicate = bad = 0; page = 1; rounds = 0
                while done < cap and not self.stop.is_set() and rounds < 100:
                    rounds += 1
                    try: result = client.search(src, query, page)
                    except Exception as exc:
                        self.events.put(('notice', f'{src}: erro na busca: {exc}')); break
                    bad += result.skipped
                    if not result.posts and not result.has_more: break
                    for post in result.posts:
                        if self.stop.is_set() or done >= cap: break
                        if post.media_type not in allowed and post.media_type != "A apurar" and not (post.url.lower().split("?")[0].endswith((".png",".webp")) and "GIFs/animações" in allowed):
                            bad += 1
                            continue
                        if self.project.known(post):
                            key, state = self.project.merge(self.project.known(post), post)
                        else:
                            try:
                                key, state = self.project.add_post(post, client, self.stop)
                            except InterruptedError: break
                            except Exception as exc:
                                bad += 1
                                self.events.put(('notice', f'{src} #{post.post_id}: {str(exc)[:120]}'))
                                continue
                        if state.startswith('duplicado'): duplicate += 1
                        else: done += 1
                        if state.startswith("duplicado"):self.progress.adjust(1)
                        if self.project.auto_extract:after_media(key)
                        else:self.progress.advance()
                        self.events.put(('new_item', key, f'{src}: {done} novas / {duplicate} duplicadas / {bad} falhas'))
                    if not result.has_more: break
                    page += 1
                self.progress.adjust(done-cap)
                summary.append(f'{src}: {done} novos · {duplicate} duplicados · {bad} falhas')
            self.events.put(('notice', 'Downloads concluídos. ' + ' | '.join(summary)))
        self._run('Baixando e preparando mídias', task, editable=True,prepare_cfg=after_media.ai_config)

    def _import_files(self):
        paths = filedialog.askopenfilenames(title='Escolher mídias', filetypes=[('Todos os arquivos','*.*')])
        if paths: self._import_paths([Path(p) for p in paths])

    def _import_folder(self):
        folder = filedialog.askdirectory(title='Selecionar pasta de imagens')
        if not folder: return
        root = Path(folder)
        recursive = self.import_recursive.get()
        paths = root.rglob('*') if recursive else root.iterdir()
        self._import_paths(p for p in paths if p.is_file() and p.suffix.lower() not in {".txt",".json",".csv"}
                           and self.project.root not in p.resolve().parents)

    def _import_paths(self, paths):
        if self.busy:return
        try:self.sync_options()
        except Exception as e:messagebox.showerror("Extrator",str(e));return
        self.project.auto_extract = True
        try:after_media=self.prepare_callback(self.import_prepare.get())
        except ValueError as e:messagebox.showinfo("Importar",str(e));return
        def task():
            total = duplicates = failed = 0
            batch=list(paths)
            self.progress.plan(len(batch))
            for p in batch:
                if self.stop.is_set(): break
                try:
                    key, state = self.project.import_file(p)
                    after_media(key)
                    duplicates += state.startswith('duplicado')
                    total += not state.startswith('duplicado')
                    self.events.put(('new_item', key, p.name+' → '+state))
                except Exception as exc:
                    failed += 1
                    self.progress.advance()
                    self.events.put(('notice',f'Falha em {p.name}: {str(exc)[:125]}'))
            self.events.put(('import_out',f'{total} novas imagens · {duplicates} duplicatas · {failed} falhas.'))
            self.events.put(('notice','Importação finalizada. Abra a aba Revisar para gerar tags e captions.'))
        self.tabs.select(self.tab_review)
        self._run('Importando arquivos',task,editable=True,prepare_cfg=after_media.ai_config)

    def on_ui(self,action):
        future=Future()
        self.events.put(("ui_call",action,future))
        return future.result()

    def draw_progress(self):
        title,done,total,complete,rows=self.progress.snapshot()
        active=self.busy and not self.stop.is_set()
        for key,(label,bar) in self.meters.items():
            if key=="work":
                value=100 if complete else min(99,100*done/total) if total else 0
                caption=f"{int(value)}% · {title}" if total or complete else title
                pulse=active and not total
            else:
                name,current,limit,ended=rows[key]
                value=100 if ended else min(99,100*current/limit) if limit else 0
                amount=f"{current/1048576:.1f} MiB" if key=="download" else ""
                state=f"{int(value)}%" if limit or ended else amount
                lane={"download":"Download","extract":"Extração","tags":"Tags","caption":"Descrições"}[key]
                caption=f"{lane} {state} · {name}"
                pulse=active and name!="Aguardando" and "interrompido" not in name and not limit and not ended
            label.configure(text=caption)
            mode="indeterminate" if pulse else "determinate"
            if str(bar.cget("mode"))!=mode:
                bar.stop()
                bar.configure(mode=mode)
                if pulse:bar.start(60)
            if not pulse:bar.configure(value=value)
            if key=="work" and hasattr(self,"train_progress"):
                train=self.train_progress
                if str(train.cget("mode"))!=mode:
                    train.stop();train.configure(mode=mode)
                    if pulse:train.start(60)
                if not pulse:train.configure(value=value)

    def _run(self, title, func, editable=False, on_success=None):
        if self.busy:
            messagebox.showwarning('Tarefa em execução','Interrompa ou conclua a tarefa atual.'); return
        self._save_edit()
        self.busy = True; self.stop.clear(); self.status.set(title + '...')
        self.editable_job=editable
        self.progress.reset(title)
        self.project.progress=self.progress.report
        def wrapper():
            success=False
            faults=0
            try:
                with ThreadPoolExecutor(max_workers=1,thread_name_prefix="caption-ia") as self.ai_worker:
                    self.pending_ai=[]
                    func()
                    for job in self.pending_ai:faults+=job.result() or 0
                success=not self.stop.is_set()
            except InterruptedError:self.events.put(("notice","Tarefa cancelada; progresso salvo."))
            except Exception as exc:self.events.put(("fail",str(exc)))
            finally:
                self.project.frame_received=lambda key:None
                result=f"Concluído · {faults} falhas de IA" if faults else "Concluído"
                self.progress.end(success,result if success else "Interrompido")
                self.events.put(("finish",success,on_success))
        if not editable:
            self.tags_text.configure(state="disabled")
            self.cap_text.configure(state="disabled")
        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()

    def _cancel(self):
        if self.busy: self.stop.set(); self.status.set('Solicitando interrupção...')

    def _refresh_tree(self):
        for k in self.tree.get_children(): self.tree.delete(k)
        self.refreshing_tree=True
        for key in reversed(list(self.project.items)):
            self._update_tree(key)
        self.refreshing_tree=False
        self._update_stats()

    def _update_tree(self, key):
        item = self.project.items.get(key)
        if item is None or item.get("removed"): return
        origin = '+'.join(sorted({o['source'] for o in item.get('origins', [])}))
        val = (origin[:15], item.get('status','pendente'), len(item.get('tags',[])), 'Sim' if item.get('krea') else 'Não')
        if self.tree.exists(key): self.tree.item(key, values=val)
        else: self.tree.insert('', 'end', iid=key, text=item['filename'][:24], values=val)
        if not getattr(self,'refreshing_tree',False):self._update_stats()

    def _update_stats(self):
        vals = [it for it in self.project.items.copy().values() if not it.get("removed")]
        approved = sum(v.get('status')=='aprovado' for v in vals)
        near = sum(bool(v.get('near_duplicates')) for v in vals)
        self.stats.set(f'{len(vals)} imagens · {approved} aprovadas · {near} semelhantes · {self.project.counters.get("duplicates",0)} duplicatas')

    def _select(self, _=None):
        chosen = self.tree.selection()
        if hasattr(self,"selection_info"):
            self.selection_info.set(f"{len(chosen)} selecionado(s) · ações de IA usam a seleção")
        if not chosen:return
        focus=self.tree.focus()
        active=focus if focus in chosen else chosen[0]
        if active==self.current_key:return
        self._save_edit()
        self.current_key = active
        item = self.project.items[self.current_key]
        path = self.project.path_for(item)
        self.current_image = None
        if path.is_file():
            try:
                with Image.open(path) as im:
                    if getattr(im,'is_animated',False): im.seek(0)
                    img = ImageOps.exif_transpose(im).convert('RGB')
                self.current_dims = img.size
                img.thumbnail((1300,1300), Image.Resampling.LANCZOS)
                self.current_image = img
            except Exception as exc:
                self.status.set('Erro na prévia: '+str(exc))
        self.crop_scale.set(item.get('crop',{}).get('scale',1.0))
        flags = ' · POSSÍVEL SEMELHANÇA' if item.get('near_duplicates') else ''
        dims=f" · {self.current_dims[0]} × {self.current_dims[1]}" if self.current_image else ""
        self.info.set(f"{item['filename']}{dims} | {len(item.get('tags',[]))} tags | {item.get('status','pendente')}{flags}")
        origin=", ".join(item.get("inherited_tags",[]))[:150]
        self.info.set(self.info.get()+(f"\nOrigem: {origin}" if origin else "")+
                      (" · Refazer IA no recorte atual" if item.get("tags_stale") or item.get("caption_stale") else "")+
                      (" · "+item["ai_error"] if item.get("ai_error") else ""))
        self._set_text(self.tags_text, item.get('sdxl',''))
        self._set_text(self.cap_text, item.get('krea',''))
        self._draw()

    @staticmethod
    def _set_text(widget, value):
        widget.delete('1.0','end'); widget.insert('1.0', value)

    def _save_edit(self):
        if (self.busy and not self.editable_job) or not self.current_key or self.current_key not in self.project.items: return
        tags = self.tags_text.get('1.0','end-1c').strip()
        cap = self.cap_text.get('1.0','end-1c').strip()
        self._store_text(self.current_key,tags,cap)

    def save_selection_edit(self):
        keys=list(self.tree.selection())
        if self.busy or not keys or self.current_key not in keys:return
        if len(keys)==1:
            self._save_edit();return
        active=self.project.items[self.current_key]
        tags=self.tags_text.get('1.0','end-1c').strip()
        cap=self.cap_text.get('1.0','end-1c').strip()
        use_tags=tags!=active.get('sdxl','')
        use_cap=cap!=active.get('krea','')
        if not use_tags and not use_cap:return
        fields=' e '.join(name for name,changed in [('tags',use_tags),('caption',use_cap)] if changed)
        if not messagebox.askyesno("Salvar edição",f"Aplicar o mesmo texto de {fields} aos {len(keys)} itens selecionados?"):return
        for key in keys:
            item=self.project.items[key]
            self._store_text(key,tags if use_tags else item.get('sdxl',''),cap if use_cap else item.get('krea',''))

    def _store_text(self,key,tags,cap):
        item=self.project.items[key]
        if tags != item.get('sdxl','') or cap != item.get('krea',''):
            if tags != item.get("sdxl",""):
                item["tags"]=canonical_tags(tags.split(","))
                item.update(tags_ready=bool(tags),tags_stale=False,tags_geom=[self.fit_mode.get(),item["crop"].copy(),int(self.resolution.get())],
                            tag_origins={t:"usuário" for t in item["tags"]},caption_stale=bool(cap))
            if cap != item.get("krea",""):
                item.update(caption_edited=True,caption_stale=False,caption_geom=[self.fit_mode.get(),item["crop"].copy(),int(self.resolution.get())])
            item['sdxl_edited'] = tags != item.get('sdxl','') or item.get('sdxl_edited',False)
            item['sdxl'] = tags; item['krea'] = cap
            self.project.save_one(key); self._update_tree(key)

    def refresh_text(self,key):
        if key!=self.current_key:return
        it=self.project.items[key]
        for widget,field in ((self.tags_text,"sdxl"),(self.cap_text,"krea")):
            if widget.get("1.0","end-1c")!=it[field]:
                self._set_text(widget,it[field])

    def _draw(self):
        if not hasattr(self,'canvas'): return
        self.canvas.delete('all')
        img = self.current_image
        if img is None:
            self.draw_bounds = None
            self.canvas.create_text(max(self.canvas.winfo_width(),2)/2,max(self.canvas.winfo_height(),2)/2,
                                    text='Selecione uma imagem · arquivos locais ou boorus', fill='white')
            return
        cw,ch=max(self.canvas.winfo_width(),20),max(self.canvas.winfo_height(),20)
        factor=min((cw-18)/img.width,(ch-18)/img.height)
        w=max(1,int(img.width*factor));h=max(1,int(img.height*factor))
        x=(cw-w)/2; y=(ch-h)/2
        self.current_photo=ImageTk.PhotoImage(img.resize((w,h),Image.Resampling.LANCZOS))
        self.canvas.create_image(x,y,anchor='nw',image=self.current_photo)
        self.draw_bounds=(x,y,w,h)
        if not self.current_key or self.fit_mode.get()!='Recortar 1:1': return
        crop=self.project.items[self.current_key].get('crop',{})
        ow,oh=self.current_dims
        side=min(ow,oh)*crop.get('scale',1)
        rx=side*w/ow/2; ry=side*h/oh/2
        cx=x+crop.get('cx',.5)*w;cy=y+crop.get('cy',.5)*h
        self.canvas.create_rectangle(cx-rx,cy-ry,cx+rx,cy+ry,outline='#f9dc63',width=3)

    def _crop_click(self, event):
        if self.busy and not self.editable_job:return
        if not self.current_key or not self.draw_bounds or self.fit_mode.get()!='Recortar 1:1': return
        x,y,w,h=self.draw_bounds
        ow,oh=self.current_dims
        crop=self.project.items[self.current_key].setdefault('crop',{'cx':.5,'cy':.5,'scale':1.0})
        hx=min(ow,oh)*crop['scale']/(2*ow)
        hy=min(ow,oh)*crop['scale']/(2*oh)
        crop['cx']=max(hx,min(1-hx,(event.x-x)/w))
        crop['cy']=max(hy,min(1-hy,(event.y-y)/h))
        self.project.items[self.current_key]['tags_stale']=True
        if self.project.items[self.current_key].get('krea'):
            self.project.items[self.current_key]['caption_stale']=True
        self._draw()

    def _crop_done(self, event=None):
        if self.busy and not self.editable_job:return
        if self.current_key: self.project.save_one(self.current_key)

    def _crop_scale_change(self, value):
        if self.busy and not self.editable_job:return
        if not self.current_key or not self.current_image: return
        crop=self.project.items[self.current_key].setdefault('crop',{'cx':.5,'cy':.5,'scale':1.0})
        if abs(crop.get('scale',1)-float(value))<0.000001:return
        crop['scale']=float(value)
        ow,oh=self.current_dims
        hx=min(ow,oh)*crop['scale']/(2*ow)
        hy=min(ow,oh)*crop['scale']/(2*oh)
        crop['cx']=max(hx,min(1-hx,crop.get('cx',.5)))
        crop['cy']=max(hy,min(1-hy,crop.get('cy',.5)))
        self.project.items[self.current_key]['tags_stale']=True
        if self.project.items[self.current_key].get('krea'):
            self.project.items[self.current_key]['caption_stale']=True
        self.project.save_one(self.current_key)
        self._draw()

    def _crop_center(self):
        if self.busy and not self.editable_job:return
        if self.current_key:
            crop=self.project.items[self.current_key].setdefault('crop',{})
            crop['cx']=crop['cy']=.5
            self.project.items[self.current_key]['tags_stale']=True
            if self.project.items[self.current_key].get('krea'):
                self.project.items[self.current_key]['caption_stale']=True
            self._draw();self.project.save_one(self.current_key)

    def _approve(self):
        if self.busy:return
        if not self.current_key:return
        self._save_edit()
        it=self.project.items[self.current_key]
        if not self.project.path_for(it).is_file():
            messagebox.showerror('Arquivo ausente', 'Imagem removida do workspace.');return
        it['status']='aprovado';self.project.save();self._update_tree(self.current_key)
        self.status.set('Imagem aprovada para exportação.')

    def _shortcut(self,action):
        if self.tabs.select()==str(self.tab_review):
            action()
            return "break"

    def _reject(self):
        if self.busy and not self.editable_job:return
        key=self.current_key
        if not key:return
        if not messagebox.askyesno("Remover da lista","Remover esta imagem do dataset? O arquivo original será preservado."):return
        self._save_edit()
        self.project.items[key].update(status="rejeitado",removed=True)
        self.project.save_one(key)
        neighbor=self.tree.next(key) or self.tree.prev(key)
        self.current_key=None
        self.current_image=None
        self.tree.delete(key)
        if self.gallery.exists(key):self.gallery.delete(key)
        self._set_text(self.tags_text,"")
        self._set_text(self.cap_text,"")
        self.info.set("Selecione uma imagem.")
        if neighbor:
            self.tree.selection_set(neighbor)
            self._select()
        self._draw()
        self._update_stats()

    def next_pending(self):
        for key, item in self.project.items.items():
            if item.get("status") == "pendente" and not item.get("removed"):
                self.tree.selection_set(key)
                self.tree.see(key)
                self._select()
                return

    def _approve_all(self):
        if self.busy:return
        if not messagebox.askyesno('Aprovar todos','Aprovar todas as imagens pendentes, inclusive as que ainda não foram revisadas?'):return
        for it in self.project.items.values():
            if it.get('status')=='pendente' and self.project.path_for(it).is_file():it['status']='aprovado'
        self.project.save();self._refresh_tree()

    def _ai_config(self, need_caption_profile=True):
        if need_caption_profile and self.profile.get()==PROFILE_SDXL:
            raise ValueError('Selecione um perfil Krea 2 ou Personalizado para usar IA.')
        provider=self.provider.get()
        if provider=='Nenhuma':raise ValueError('Escolha um provedor de IA.')
        # If a preset was edited, respect it for the current session too.
        prompt = self.prompt.get('1.0','end-1c').strip()
        if not prompt:
            if need_caption_profile: raise ValueError('Prompt de caption vazio.')
            prompt = get_profile_prompt(PROFILE_DETAILED)
        api=self.api_url.get().strip()
        tokens=int(self.token_limit.get())
        if not 32<=tokens<=4096:raise ValueError("Use de 32 a 4096 tokens.")
        return AIConfig(provider,self.model.get().strip(),self.api_key.get().strip(),prompt,
                        self.trigger.get().strip(),ollama_url=api if provider=='Ollama (local)' else 'http://127.0.0.1:11434',
                        llama_url=api if provider=='llama.cpp (local)' else 'http://127.0.0.1:8080',max_tokens=tokens)

    def _test_llama(self):
        try:
            cfg=self._ai_config(False)
            if cfg.provider != 'llama.cpp (local)':raise ValueError('Selecione llama.cpp (local).')
        except Exception as exc:
            messagebox.showerror('Configuração',str(exc));return
        def task():self.events.put(('info_dialog',test_llama_vision(cfg)))
        self._run('Testando visão do llama.cpp',task,prepare_cfg=cfg)

    def _tag_current(self):self.ai_queue("tags",selected=True)
    def _caption_current(self):self.ai_queue("caption",selected=True,force=True)
    def _tag_batch(self):self.ai_queue("tags")
    def _caption_batch(self):self.ai_queue("caption")
    def _caption_regen(self):self.ai_queue("caption",force=True)

    def _choose_output(self):
        folder=filedialog.askdirectory(title='Escolher destino do dataset')
        if folder:self.output.set(folder)

    def _export(self):
        self._save_edit()
        approved=[it for it in self.project.items.values() if it.get('status')=='aprovado']
        if not approved:messagebox.showwarning('Exportar','Aprove pelo menos uma imagem.');return
        mode=self.caption_mode.get()
        if mode in ('SDXL','Ambos') and any(it.get('tags_stale') for it in approved):
            if not messagebox.askyesno('Tags desatualizadas','Exportar as tags anteriores ao recorte atual?'):return
        if mode in ('Krea2','Ambos') and any(it.get('caption_stale') for it in approved):
            if not messagebox.askyesno('Recorte alterado', 'Algumas imagens tiveram o recorte modificado depois da última descrição. Regenerar as captions antes de exportar é recomendado. Continuar mesmo assim?'): return
        if mode in ('Krea2','Ambos') and any(not it.get('krea') for it in approved):
            if not messagebox.askyesno('Legendas vazias','Algumas imagens não têm caption Krea2. Exportar mesmo assim?'):return
        out=Path(self.output.get());size=int(self.resolution.get());fit=self.fit_mode.get();fmt=self.image_format.get()
        if not messagebox.askyesno('Confirmar exportação',f'Exportar {len(approved)} imagens para:\n{out}\n{mode} · {size}px · {fit} · {fmt}\nUse uma pasta vazia.'):return
        def task():
            count,errors=self.project.export(out,mode,size,fit,fmt,self.stop,
                                             lambda n,total:(self.progress.plan(total),self.progress.advance()))
            self.events.put(('info_dialog',f'{count} imagens exportadas.\n{len(errors)} falhas.\nDestino: {out}'))
            if errors:self.events.put(('notice','Falhas: '+str(errors[:3])))
        self._run('Exportando dataset',task)

    def _reset(self):
        if self.busy:messagebox.showwarning('Em execução','Interrompa a tarefa antes.');return
        if not messagebox.askyesno('NOVO PROJETO','Limpar a lista, as legendas e todo o progresso do workspace atual?\n\nDatasets já exportados não serão apagados.'):
            return
        delete=messagebox.askyesno('Apagar cópias','Apagar também os arquivos temporários baixados/importados no workspace?\n\nA pasta local original não será afetada.')
        self.project.reset(delete);self.refresh_gallery()
        self.current_key=None;self.current_image=None
        self._set_text(self.tags_text,'');self._set_text(self.cap_text,'');self.info.set('Projeto novo: lista vazia.')
        self._refresh_tree();self._draw();self.status.set('Workspace zerado. Inicie nova busca ou importação.')

    def _change_workspace(self):
        if self.busy:messagebox.showwarning('Em execução','Interrompa a tarefa antes.');return
        folder=filedialog.askdirectory(title='Selecionar outro workspace',initialdir=str(self.project.root))
        if not folder:return
        self._save_edit();self.project.close();self.project=Dataset(Path(folder));self.refresh_gallery()
        for name,var in self.extract_vars.items():var.set(getattr(self.project.settings,name))
        self.current_key=None;self.current_image=None
        self._set_text(self.tags_text,'');self._set_text(self.cap_text,'')
        self._refresh_tree();self._draw();self.status.set('Workspace: '+folder)

    def _log(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0','end');widget.insert('1.0',text)
        widget.configure(state='disabled')

    def _poll(self):
        try:
            for _ in range(70):
                try:packet=self.events.get_nowait()
                except queue.Empty:break
                name,*args=packet
                if name=='ui_call':
                    action,future=args
                    try:future.set_result(action())
                    except Exception as exc:future.set_exception(exc)
                elif name=='new_item':
                    key,desc=args
                    self._update_tree(key)
                    self.status.set(desc)
                    if self.tree.exists(key) and self.follow_new.get() and self.current_key is None:
                        self.tree.selection_set(key);self._select()
                elif name=='search_out':self._log(self.search_out,args[0])
                elif name=='import_out':self._log(self.import_out,args[0])
                elif name=='notice':self.status.set(args[0])
                elif name=='info_dialog':messagebox.showinfo('Caption Create',args[0])
                elif name=='fail':messagebox.showerror('Erro',args[0]);self.status.set('Erro: '+args[0][:160])
                elif name=='finish':
                    keep_selection=self.tree.selection()
                    if self.editable_job:self._save_edit()
                    self.editable_job=False
                    self.busy=False
                    self.tags_text.configure(state='normal');self.cap_text.configure(state='normal')
                    key=self.current_key
                    self.current_key=None
                    self._refresh_tree()
                    self.refresh_gallery()
                    if key and self.tree.exists(key):
                        self.tree.selection_set([k for k in keep_selection if self.tree.exists(k)] or [key]);self.tree.focus(key)
                        self._select()
                    if len(args)>1 and args[0] and not self.stop.is_set() and args[1]:args[1]()
                    if hasattr(self,"complete_media"):self.complete_media(bool(args and args[0]))
        finally:
            self.draw_progress()
            self.after(80,self._poll)

    def _close(self):
        if self.busy:
            if not messagebox.askyesno('Tarefa ativa','Sair e interromper a operação em andamento?'):return
            self.stop.set()
        self._save_edit()
        if self.busy:
            self.after(200,self._wait_close)
            return
        self.project.close()
        self.quit()
        self.destroy()

    def _wait_close(self):
        if self.busy:self.after(200,self._wait_close)
        else:self._close()


if __name__=='__main__':
    CaptionCreate().mainloop()
