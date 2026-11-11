from dataclasses import replace
import os
import shutil
import sys
import time
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image,ImageTk
import psutil
sys.path.insert(0,str(Path(__file__).parent/"caption"))
from app import CaptionCreate
import app as caption_ui
from configuracao import ROOT,DATA,CONF,discover,gpu,read_json,write_json
from ambiente import PROFILES,PYTHON,LORAS,environment
from calibrar import SIZES,MARGIN,report,signature,FILE,targets
from revisao import preview,approve,ready,selected,materialize,import_project,state
from galeria import Gallery
from processos import Owned,start_caption
from dataset import Dataset

from legendas import Legendas
from pipeline import Pipeline

class Hydra(Pipeline,Legendas,CaptionCreate):
    def __init__(self,project_name=None):
        self.caption_process=None
        self.foreground=None
        self.validated=None
        self.cfg=discover()
        self.session=DATA/"sessao.json"
        projects=DATA/"projetos"
        last=read_json(self.session,{}).get("projeto","Principal")
        caption_ui.DEFAULT_ROOT=projects/Path(project_name or last).name
        from studio_shell import log
        log.info("Criação da raiz e carga do projeto")
        super().__init__(deferred=True)
        from studio_shell import startup_logging
        startup_logging(self)

    def free_memory(self):
        if self.busy:
            self.status.set("Aguarde a conclusão da tarefa para liberar memória.")
            return
        import gc
        self.release_caption()
        self.tiles.cache.clear()
        self.tiles.queue()
        gc.collect()
        self.status.set("Limpeza concluída · cache de miniaturas e modelo visual local liberados.")
    def update_free_vram(self):
        try:
            import pynvml as nv
            if not getattr(self,"vram_handle",None):
                if not getattr(self,"card",None):
                    self.after(3000,self.update_free_vram);return
                nv.nvmlInit()
                self.vram_handle=nv.nvmlDeviceGetHandleByUUID(self.card["uuid"])
            mem=nv.nvmlDeviceGetMemoryInfo(self.vram_handle)
            self.hardware_short.set(f"VRAM livre   {mem.free/2**30:.1f} / {mem.total/2**30:.1f} GiB")
        except Exception:
            self.hardware_short.set("VRAM livre indisponível")
        self.after(3000,self.update_free_vram)
    def _after_ready(self):
        self.after(500,self.update_free_vram)
        self.title("HydraTrainStudio")
        self.minsize(min(1100,self.winfo_screenwidth()-60),min(720,self.winfo_screenheight()-100))
        self.status.set("Pronto")
        self.tabs.select(self.home_page)
        self.restore()
        welcome=DATA/"componentes-apresentados"
        if not CONF.exists() and not welcome.exists():
            welcome.touch()
            self.after(250,self.install_dialog)
    def _ui(self):
        self.shell()
        self.family=tk.StringVar(value="Krea2");self.preset=tk.StringVar(value="Ideal")
        self.hw=tk.StringVar();self.res_label=tk.StringVar()
        hardware=ttk.LabelFrame(self.tab_project,text="Hardware e preset",padding=14);hardware.pack(fill="x",pady=8)
        ttk.Label(hardware,textvariable=self.hw,wraplength=1000).pack(anchor="w",pady=8)
        row=self.row(hardware)
        for var,values in ((self.family,PROFILES),(self.preset,tuple(MARGIN))):
            box=ttk.Combobox(row,textvariable=var,values=values,state="readonly",width=18);box.pack(side="left",padx=3)
            box.bind("<<ComboboxSelected>>",self.change_preset)
        ttk.Label(row,textvariable=self.res_label).pack(side="left",padx=10)
        ttk.Button(row,text="Calibrar preset",command=self.calibrate).pack(side="left")
        ttk.Label(hardware,text="O alvo é quadrado. O recorte e a ampliação são conferidos individualmente na revisão.").pack(anchor="w",pady=6)
        self.components=ttk.LabelFrame(self.component_panel,text="Componentes locais",padding=8);self.components.pack(fill="x",pady=10)
        self.config_fields={}
        for key,label in (("treino","Biblioteca de treino"),("modelos","Pesos de base"),("comfy","Instalação ComfyUI"),
                          ("python_comfy","Python do ComfyUI"),("servidor","llama-server.exe"),("modelo_caption","Modelo visual GGUF"),("projetor","Projetor visual GGUF"),("modelo_think","Modelo visual Think GGUF"),("projetor_think","Projetor visual Think GGUF")):
            row=self.row(self.components,1);ttk.Label(row,text=label,width=22).pack(side="left")
            var=tk.StringVar(value=self.cfg.get(key,""));self.config_fields[key]=var
            ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)
            ttk.Button(row,text="Localizar…",command=lambda k=key:self.locate(k)).pack(side="left")
        ttk.Button(self.components,text="Salvar caminhos",command=self.save_components).pack(anchor="e")
        ttk.Button(self.component_panel,text="Instalação de componentes…",command=self.install_dialog).pack(anchor="w")
        self.compat=tk.StringVar();ttk.Label(hardware,textvariable=self.compat,wraplength=1000).pack(anchor="w",pady=6)
        row=self.row(self.tab_import)
        ttk.Button(row,text="Importar banco ou manifesto…",command=lambda:self.import_ready(False)).pack(side="left")
        ttk.Button(row,text="Importar dataset ou projeto…",command=lambda:self.import_ready(True)).pack(side="left",padx=5)
        self.name_var=tk.StringVar(value="Meu-LoRA");self.steps=tk.StringVar(value="0");self.interval=tk.StringVar(value="0");self.lr=tk.StringVar(value="0.0001")
        top=ttk.Frame(self.tab_train);top.pack(fill="x")
        top.columnconfigure(0,weight=72,uniform="train");top.columnconfigure(1,weight=28,uniform="train")
        form=ttk.Frame(top);form.grid(row=0,column=0,sticky="nsew",padx=(0,8))
        data=ttk.LabelFrame(form,text="Dataset",padding=12);data.pack(fill="x",pady=4)
        ttk.Label(data,textvariable=self.workspace_text,wraplength=420).pack(anchor="w")
        ttk.Button(data,text="Revisar dataset",command=lambda:self.tabs.select(self.tab_review)).pack(anchor="w",pady=3)
        params=ttk.LabelFrame(form,text="Configurações do treino",padding=12);params.pack(fill="x",pady=6)
        for title,var in (("Nome do LoRA",self.name_var),("Passos (0 = automático)",self.steps),("Checkpoint (0 = automático)",self.interval),("Taxa de aprendizado",self.lr)):
            self.field(params,title,var)
        from avancado import controls
        controls(self,params)
        self.train_btn=ttk.Button(form,text="Preparar dataset e iniciar treino",command=self.train,style="Primary.TButton")
        self.train_btn.pack(fill="x",pady=6)
        side=ttk.LabelFrame(top,text="Projeto e ferramentas",padding=12);side.grid(row=0,column=1,sticky="nsew",padx=(8,0),pady=4)
        ttk.Label(side,textvariable=self.project_label,style="Metric.TLabel").pack(anchor="w")
        self.summary=tk.StringVar()
        ttk.Label(side,textvariable=self.summary,wraplength=200).pack(anchor="w",pady=8)
        self.train_previews=ttk.Frame(side);self.train_previews.pack(fill="x",pady=4)
        self.train_previews.bind("<Map>",lambda _:self.after_idle(self.draw_train_samples))
        ttk.Button(side,text="Ver LoRAs",command=self.open_loras).pack(fill="x",pady=2)
        ttk.Button(side,text="Testar e comparar",command=lambda:self.train_book.select(self.tab_gallery)).pack(fill="x",pady=2)
        log_panel=ttk.LabelFrame(self.tab_train,text="Log de treinamento",padding=10);log_panel.pack(fill="both",expand=True,pady=8)
        self.log=tk.Text(log_panel,width=1,height=9,wrap="word");self.log.pack(side="left",fill="both",expand=True)
        progress=ttk.Frame(log_panel,width=190);progress.pack(side="right",fill="y",padx=8)
        ttk.Label(progress,textvariable=self.status,wraplength=175).pack(anchor="w")
        self.train_progress=ttk.Progressbar(progress,maximum=100);self.train_progress.pack(fill="x",pady=8)
        ttk.Button(progress,text="Parar tarefa",command=self._cancel).pack(fill="x")
        self.gallery_ui=Gallery(self,self.tab_gallery)
        self.steps.trace_add("write",lambda *_:self._update_stats())
        self.interval.trace_add("write",lambda *_:self._update_stats())
        self.tabs.bind("<<NotebookTabChanged>>",lambda _:self._update_stats(),add="+")
        self.finish_layout()
    def draw_train_samples(self):
        if not self.train_previews.winfo_ismapped():return
        from itertools import islice
        paths=[self.project.path_for(it) for it in islice((it for it in self.project.items.values() if selected(it)),3)]
        if paths==getattr(self,"sample_paths",None):return
        self.sample_paths=paths
        for child in self.train_previews.winfo_children():child.destroy()
        for path in paths:
            try:
                with Image.open(path) as im:
                    im.thumbnail((54,54))
                    photo=ImageTk.PhotoImage(im)
            except (OSError,ValueError):continue
            label=ttk.Label(self.train_previews,image=photo);label.image=photo;label.pack(side="left",padx=1)
    def restore(self):
        saved=read_json(self.project.root/"hydra.json",{})
        self.family.set(saved.get("perfil","Krea2"));self.preset.set(saved.get("preset","Ideal"))
        self.apply(preserve=True)
        write_json(self.session,{"projeto":self.project.root.name})
    def change_preset(self,_=None):
        if self.busy:
            saved=read_json(self.project.root/"hydra.json",{})
            self.family.set(saved.get("perfil","Krea2"));self.preset.set(saved.get("preset","Ideal"))
            return
        self._save_edit();self.apply()
    def apply(self,preserve=False):
        profile,preset=self.family.get(),self.preset.get()
        target=SIZES[profile][preset][0]
        self.request_hardware(profile,preset,preserve)
        cached=getattr(self,"hardware_result",{}).get((profile,preset))
        self.validated=None
        if cached:
            self.card,self.validated,summary=cached
            self.hw.set(summary)
        else:self.hw.set("Verificando hardware…")
        size=self.validated or target
        prev=read_json(self.project.root/"hydra.json",{})
        if preserve and prev.get("res") and prev.get("perfil")==profile and prev["res"]!=size:
            size=prev["res"]
            self.validated=None
        if prev and (prev.get("perfil"),prev.get("res"))!=(profile,size):
            for it in self.project.items.values():
                if selected(it):
                    it.pop("hydra_aprovacao",None);it["status"]="pendente"
            self.project.save()
        from ambiente import RAW,TURBO,ENC_K,ENC_A,VAE,ANIMA,XL,COMFY
        weights={"Krea2":[RAW,TURBO,ENC_K,VAE],"Anima":[ANIMA,ENC_A,VAE],"Illustrious":[XL]}[profile]
        missing=[f.name for f in weights if not f.is_file()]
        self.compat.set("Motor de treino: "+("localizado" if PYTHON.is_file() else "ausente")+
                        " · ComfyUI: "+("localizado" if (COMFY/"ComfyUI/main.py").is_file() and Path(self.cfg["python_comfy"]).is_file() else "ausente")+
                        " · "+("Pesos ausentes: "+", ".join(missing) if missing else "Pesos do perfil localizados"))
        self.resolution.set(str(size));self.caption_mode.set("Krea2" if profile=="Krea2" else "SDXL")
        self.res_label.set(f"Alvo {target} · "+(f"validado {size} px" if self.validated else "aguardando calibração"))
        updated={**prev,"perfil":profile,"preset":preset,"res":size}
        if updated!=prev:write_json(self.project.root/"hydra.json",updated)
        self._refresh_tree()
    def request_hardware(self,profile,preset,preserve):
        if getattr(self,"hardware_loading",False):return
        if (profile,preset) in getattr(self,"hardware_result",{}):return
        self.hardware_loading=True
        from threading import Thread
        from concurrent.futures import Future
        from studio_shell import log
        log.info("Início verificação secundária do hardware")
        def work():
            try:
                card=gpu()
                measured=report(profile,preset,card)
                mem=psutil.virtual_memory()
                summary=f"{card['name']} · VRAM {card['free']} / {card['total']} MiB livres · RAM {mem.available/2**30:.1f} / {mem.total/2**30:.1f} GiB · disco {shutil.disk_usage(DATA).free/2**30:.0f} GiB livres"
                def commit():
                    self.hardware_loading=False
                    if not hasattr(self,"hardware_result"):self.hardware_result={}
                    self.hardware_result[(profile,preset)]=(card,measured,summary)
                    log.info("Fim verificação secundária do hardware")
                    if (self.family.get(),self.preset.get())==(profile,preset):self.apply(preserve=preserve)
                    else:self.apply(preserve=True)
            except Exception as exc:
                message=str(exc)
                def commit():
                    self.hardware_loading=False
                    self.hw.set("Hardware indisponível: "+message)
                    log.error("Falha na verificação secundária: %s",message)
            self.events.put(("ui_call",commit,Future()))
        Thread(target=work,daemon=True).start()

    def locate(self,key):
        result=filedialog.askdirectory() if key in ("treino","modelos","comfy") else filedialog.askopenfilename()
        if result:self.config_fields[key].set(result)
    def save_components(self):
        if self.busy:return
        write_json(CONF,{k:v.get() for k,v in self.config_fields.items()})
        messagebox.showinfo("Componentes","Caminhos salvos. Feche e reabra o HydraTrainer para aplicá-los.")
    def install_dialog(self):
        if self.busy:return
        subprocess.Popen([sys.executable,str(ROOT/"app/componentes.py")])
    def calibrate(self):
        if self.busy:return
        if self.preset.get()=="Experimental" and not messagebox.askyesno("Experimental","O teste pode esgotar a VRAM. Executar a calibração?"):return
        def updated():
            self.hardware_result={}
            self.apply()
        self.execute("Calibrando","calibrar.py",[self.family.get(),self.preset.get()],updated)
    def release_caption(self):
        if self.caption_process:
            self.caption_process.close();self.caption_process=None
            url,model=self.previous_caption_config
            self.api_url.set(url);self.model.set(model)
    def launch_qwen(self,thinking=None):
        if self.busy:return
        cfg=self._ai_config(False)
        self._run("Iniciando modelo visual",lambda:None,prepare_cfg=cfg)

    def _ai_config(self,need_caption_profile=True):
        thinking=self.provider.get()=="llama.cpp (local)" and self.vision_think.get()
        joy=self.vision_choice.get()=="JoyCaption Beta One"
        if joy and self.provider.get()!="llama.cpp (local)":
            raise ValueError("Selecione llama.cpp (local) para usar JoyCaption ou escolha Padrão no perfil.")
        if joy and not self.cfg.get("servidor"):raise ValueError("Configure o executável llama-server para usar JoyCaption.")
        if joy:thinking=False
        cfg=replace(super()._ai_config(need_caption_profile),thinking=thinking)
        if cfg.provider=="llama.cpp (local)" and self.cfg.get("servidor") and (joy or self.caption_process or self.api_url.get() in ("http://127.0.0.1:8080","")):
            cfg._managed_files=dict(self.cfg)
            if joy:
                folder=ROOT/"componentes/joycaption"
                if not folder.is_dir():folder=Path(self.cfg["treino"])/"models/joycaption"
                if not folder.is_dir():raise ValueError("Instale JoyCaption Beta One em Configurações → Componentes.")
                cfg._managed_files.update(modelo_caption=str(folder/"Llama-Joycaption-Beta-One-Hf-Llava-Q4_K_M.gguf"),
                                          projetor=str(folder/"llama-joycaption-beta-one-llava-mmproj-model-f16.gguf"))
            cfg._previous_config=self.previous_caption_config if self.caption_process else (self.api_url.get(),self.model.get())
        return cfg

    def _run(self,title,func,editable=False,on_success=None,prepare_cfg=None):
        def prepared():
            cfg=prepare_cfg
            if cfg is not None and hasattr(cfg,"_managed_files"):
                files=cfg._managed_files
                thinking=cfg.thinking
                if thinking:files={**files,"modelo_caption":files.get("modelo_think",""),"projetor":files.get("projetor_think","")}
                identity=(files.get("servidor"),files.get("modelo_caption"),files.get("projetor"),thinking)
                def current():
                    if self.caption_process and self.caption_process.proc.poll() is None and self.managed_identity==identity:
                        return self.caption_process,self.api_url.get()
                    self.release_caption()
                    return None,None
                proc,url=self.on_ui(current)
                if proc is None:
                    proc,url=start_caption(files,DATA/"logs/caption.log",thinking=thinking)
                    def register():
                        self.previous_caption_config=cfg._previous_config
                        self.caption_process=proc;self.managed_identity=identity
                        self.api_url.set(url);self.model.set("hydra-vision")
                    self.on_ui(register)
                cfg.llama_url=url;cfg.model="hydra-vision"
            func()
        super()._run(title,prepared,editable=editable,on_success=on_success)

    def import_ready(self,is_folder):
        if self.busy:return
        path=filedialog.askdirectory() if is_folder else filedialog.askopenfilename(filetypes=[("Projeto ou manifesto","*.sqlite *.db *.sqlite3 *.json")])
        if not path:return
        self._save_edit()
        profile=self.family.get()
        def task():
            proj=import_project(Path(path),profile)
            self.on_ui(lambda:self.adopt(proj))
        self.tabs.select(self.tab_review)
        self._run("Importando dataset para revisão",task)
    def adopt(self,project):
        self.project.close();self.project=project
        self.current_key=None;self.current_image=None
        for name,var in self.extract_vars.items():var.set(getattr(project.settings,name))
        self.workspace_text.set(str(project.root));self.project_label.set(project.root.name);self.load_prompts();self.info.set("Selecione uma imagem para revisar.")
        self.refresh_gallery();self._set_text(self.tags_text,"");self._set_text(self.cap_text,"")
        if (project.root/"hydra.json").exists():self.restore()
        else:self.apply();write_json(self.session,{"projeto":project.root.name})
        self.tabs.select(self.tab_review)
        self._draw()
    def _change_workspace(self):
        if self.busy:return
        folder=filedialog.askdirectory(initialdir=DATA/"projetos",title="Abrir projeto HydraTrainer")
        if not folder:return
        path=Path(folder).resolve()
        if path.parent!=(DATA/"projetos").resolve():
            messagebox.showinfo("Projetos","Para um projeto externo, use Importar dataset ou projeto na aba de importação.");return
        self._save_edit();self.adopt(Dataset(path))
    def _reset(self):
        if self.busy:return
        name=simpledialog.askstring("Novo projeto","Nome do novo projeto")
        if not name:return
        if Path(name).name!=name or name in (".","..") or any(c in name for c in '<>:"/\\|?*'):
            messagebox.showerror("Projeto","Nome de pasta inválido.");return
        path=DATA/"projetos"/name
        if path.exists():messagebox.showinfo("Projeto","Esse projeto já existe. Use Abrir projeto.");return
        self._save_edit();self.adopt(Dataset(path))
    def approve_selection(self):
        keys=list(self.tree.selection())
        if self.busy or not keys:return
        if len(keys)==1:
            self._select()
            self._approve()
        else:self.approve_batch(keys)

    def approve_and_train(self):
        keys=[k for k,it in self.project.items.items() if selected(it)]
        self.approve_batch(keys,start_train=True)

    def approve_batch(self,keys,start_train=False):
        if self.busy:return
        self._save_edit()
        project=self.project
        profile=self.family.get()
        size=int(self.resolution.get())
        if not self.validated:
            messagebox.showinfo("Preset","Calibre o preset atual antes de aprovar.");return
        if not keys:
            messagebox.showinfo("Projeto","O projeto não contém itens para aprovar.");return
        pending=[];missing=[]
        for key in keys:
            it=project.items[key]
            if not state(it,profile,size)["legenda"]:missing.append(it["filename"])
            if not ready(it,profile,size):pending.append(key)
        if missing:
            messagebox.showinfo("Legendas pendentes",f"{len(missing)} item(ns) sem legenda para {profile}. Primeiro arquivo: {missing[0]}");return
        label="Aprovar tudo e treinar" if start_train else "Aprovar seleção"
        question=f"Usar os recortes e legendas atuais de {len(keys)} item(ns) em {profile} a {size} px?"
        if start_train:question+=" O treino começará ao concluir a aprovação."
        if not messagebox.askyesno(label,question):return
        def prepare():
            self.progress.plan(len(pending))
            for k in pending:
                if self.stop.is_set():raise InterruptedError()
                im=preview(project,k,size)
                try:approve(project,k,profile,size,im)
                finally:im.close()
                self.progress.advance()
        def launch():
            self.tabs.select(self.training_tab);self.train_book.select(self.tab_train)
            self.train()
        self._run(label,prepare,on_success=launch if start_train else None)

    def _approve(self):
        if self.busy or not self.current_key:return
        if not self.validated:
            messagebox.showinfo("Preset","Calibre este preset na aba Ambiente antes de confirmar o tamanho.");return
        self._save_edit()
        key=self.current_key;it=self.project.items[key];profile=self.family.get();size=int(self.resolution.get())
        stamp=state(it,profile,size)
        if not stamp["legenda"]:
            if messagebox.askyesno("Legenda pendente","Gerar agora a legenda para este enquadramento?"):
                self.captions_profile(single=True)
            return
        image=preview(self.project,key,size)
        dialog=tk.Toplevel(self);dialog.title("Confirmar a imagem de treino");dialog.transient(self);dialog.grab_set()
        from aprovacao import layout_preview
        side=min(self.current_dims)*it.get("crop",{}).get("scale",1)
        transform="ampliação" if side<size else "redução" if side>size else "escala original"
        info=f"Original {self.current_dims[0]} × {self.current_dims[1]} → {size} × {size} · {transform}"
        from regioes import confirmed_notes
        notes=confirmed_notes(it)
        if notes:info+="\n"+self.ui_text("Notas confirmadas")+": "+" · ".join(notes)
        layout_preview(self,dialog,image,info,stamp["legenda"])
        def confirm():
            if stamp!=state(it,self.family.get(),int(self.resolution.get())):
                dialog.destroy();messagebox.showerror("Revisão","Imagem ou legenda alterada. Abra a prévia novamente.");return
            approve(self.project,key,profile,size,image)
            it["caption_stale" if profile=="Krea2" else "tags_stale"]=False
            self.project.save_one(key)
            dialog.destroy();self._update_tree(key);self.status.set("Prévia e legenda aprovadas.")
        def zoom():
            win=tk.Toplevel(dialog);win.title(f"Pixels da imagem de treino · {size} × {size}")
            win.transient(dialog)
            area=tk.Canvas(win,width=min(size,win.winfo_screenwidth()-100),height=min(size,win.winfo_screenheight()-150))
            horizontal=ttk.Scrollbar(win,orient="horizontal",command=area.xview)
            vertical=ttk.Scrollbar(win,orient="vertical",command=area.yview)
            area.configure(xscrollcommand=horizontal.set,yscrollcommand=vertical.set,scrollregion=(0,0,size,size))
            horizontal.pack(side="bottom",fill="x");vertical.pack(side="right",fill="y");area.pack(fill="both",expand=True)
            photo=ImageTk.PhotoImage(image);area.photo=photo
            area.create_image(0,0,image=photo,anchor="nw")
            win.grab_set();win.protocol("WM_DELETE_WINDOW",lambda:(win.destroy(),dialog.grab_set()))
        ttk.Button(dialog,text="Inspecionar em tamanho real (1:1)",command=zoom).grid(row=3,column=0,sticky="ew",padx=8,pady=2)
        ttk.Button(dialog,text="Confirmar enquadramento e legenda",command=confirm,style="Primary.TButton").grid(row=4,column=0,sticky="ew",padx=8,pady=2)
        ttk.Button(dialog,text="Voltar e ajustar",command=dialog.destroy).grid(row=5,column=0,sticky="ew",padx=8,pady=(2,6))
    def next_pending(self):
        for k,it in self.project.items.items():
            if selected(it) and not ready(it,self.family.get(),int(self.resolution.get())):
                self.tree.selection_set(k);self.tiles.see(k);self._select();return
        self.status.set("Nenhum item pendente.")
    def _update_stats(self):
        if getattr(self,"refreshing_tree",False):return
        if hasattr(self,"tiles"):self.tiles.queue()
        if not hasattr(self,"summary"):
            return super()._update_stats()
        profile=self.family.get();size=int(self.resolution.get())
        items=[v for v in self.project.items.values() if selected(v)]
        n=len(items);count=sum(ready(it,profile,size) for it in items)
        if hasattr(self,"home_summary"):
            frames=sum(it.get("pts_ms") is not None for it in items)
            captions=sum(bool(it.get("krea")) for it in items)
            tagged=sum(bool(it.get("sdxl") or it.get("tags")) for it in items)
            media=dict(self.project.db.execute("SELECT kind,count(*) FROM media GROUP BY kind"))
            for var,value in zip(self.metrics,(media.get("image",0),media.get("video",0),frames,tagged,captions)):var.set(str(value))
            duplicates=sum(it.get("status")=="duplicado" for it in self.project.items.values())
            self.review_summary.set(f"Imagens de treino   {n}\nFrames   {frames}\nCom tags   {tagged}\nCom caption   {captions}\nAprovadas   {count}\nDuplicadas   {duplicates}\n\nResolução alvo   {size} × {size}")
            self.home_summary.set(f"{self.project.root.name}\n{profile} · {size} × {size}\n{n} itens · {frames} frames · {captions} captions · {count} aprovados · {n-count} pendentes")
        self.stats.set(f"{count} prontos · {n-count} pendentes · {len(self.project.items)-n} excluídos")
        try:
            steps=int(self.steps.get());interval=int(self.interval.get())
            if steps<0 or interval<0:raise ValueError
            steps=steps or max(300,min(2000,n*35)); interval=interval or max(100,steps//4)
            from avancado import options,target_steps
            opts=options({k:v.get() for k,v in self.advanced_vars.items()},steps,n) if self.advanced_mode.get() else {}
            if opts:
                steps=target_steps(opts,steps,n)
                interval=int(self.interval.get()) or max(100,steps//4)
            batch=opts.get("batch",1);accum=opts.get("accum",1)
            self.summary.set(f"{profile} · {size} × {size} · {n} imagens · lote {batch} × {accum} · {steps} passos · {steps*batch*accum/max(n,1):.1f} épocas equivalentes · checkpoint a cada {interval} passos\nSaída: {LORAS/profile}")
            valid=True
        except ValueError as exc:
            self.summary.set(str(exc) or "Use números inteiros positivos ou 0 para automático.");valid=False
        self.train_btn.configure(state="normal" if valid and self.validated and n and count==n and not self.busy else "disabled")
    def _crop_done(self,event=None):
        super()._crop_done(event)
        if self.current_key:self._update_tree(self.current_key)
    def _crop_scale_change(self,value):
        super()._crop_scale_change(value)
        if self.current_key:self._update_tree(self.current_key)
    def _crop_center(self):
        super()._crop_center()
        if self.current_key:self._update_tree(self.current_key)
    def _update_tree(self,key):
        super()._update_tree(key)
        if hasattr(self,"family") and self.tree.exists(key):
            it=self.project.items[key]
            if selected(it) and not ready(it,self.family.get(),int(self.resolution.get())):
                self.tree.set(key,"state","pendente")
    def open_loras(self):
        path=LORAS/self.family.get();path.mkdir(parents=True,exist_ok=True);os.startfile(path) if os.name=="nt" else subprocess.Popen(["xdg-open",str(path)])
    def train(self):
        if self.busy:return
        self._save_edit()
        try:
            profile=self.family.get();preset=self.preset.get();size=int(self.resolution.get())
            if not self.validated:raise ValueError("Calibre o preset primeiro.")
            self.release_caption()
            card=gpu()
            sample=read_json(FILE,{})[signature(card)][profile][str(size)]
            margin,ram=MARGIN[preset]
            need=sample.get("livre_gpu_inicio",card["total"]-1024)-sample["livre_gpu_min"]+margin
            # Older measurements did not retain the initial RAM reading.
            demand=max(ram,sample.get("livre_ram_inicio",min(22000,int(psutil.virtual_memory().total//2**20*.68)))-sample["livre_ram_min"]+ram)
            if card["free"]<need or psutil.virtual_memory().available//2**20<demand:
                raise ValueError(f"Memória livre insuficiente para a medição atual (VRAM livre {card['free']} MiB, estimada {need} MiB; RAM livre {psutil.virtual_memory().available//2**20} MiB, estimada {demand} MiB).")
            if preset=="Experimental" and not messagebox.askyesno("Experimental","Iniciar treino com a margem experimental?"):return
            lr=float(self.lr.get().replace(",","."))
            if not 0 < lr <= .01:raise ValueError("Taxa de aprendizado precisa estar entre 0 (exclusivo) e 0,01.")
            extra=[]
            if self.advanced_mode.get():
                from avancado import options,target_steps
                import json
                n=sum(selected(it) for it in self.project.items.values())
                values=options({k:v.get() for k,v in self.advanced_vars.items()},int(self.steps.get()) or max(300,min(2000,n*35)),n)
                extra=["--avancado",json.dumps(values)]
            dataset=materialize(self.project,profile,size)
            def done():
                runs=sorted((LORAS/profile).glob("*/treino.json"),key=lambda p:p.stat().st_mtime,reverse=True)
                run=next((p.parent for p in runs if read_json(p)["origem"]==str(dataset)),None)
                if run:self.move_to_tests(run)
            self.execute("Treinando","treinar.py",[profile,str(dataset),self.name_var.get(),"--res",str(size),
                         "--passos",self.steps.get(),"--intervalo",self.interval.get(),"--taxa",str(lr),*extra],done)
        except Exception as e:messagebox.showerror("Treino",str(e))
    def execute(self,title,script,args,after):
        if self.busy:return
        self.release_caption()
        logdir=DATA/"logs";logdir.mkdir(exist_ok=True)
        log=logdir/(time.strftime("%Y%m%d-%H%M%S")+"-"+script+".log")
        env=environment();env["PYTHONDONTWRITEBYTECODE"]="1"
        if script!="mesclar.py":env["CUDA_VISIBLE_DEVICES"]=gpu()["index"]
        if not PYTHON.is_file():messagebox.showerror("Ambiente","Instale ou localize o motor de treino na aba Ambiente.");return
        self.log.delete("1.0","end")
        def job():
            with log.open("w",encoding="utf-8") as sink, log.open("r",encoding="utf-8",errors="replace") as reader:
                owner=Owned([str(PYTHON),"-u",str(Path(__file__).with_name(script)),*args],env=env,stdout=sink,stderr=subprocess.STDOUT)
                self.foreground=owner
                try:
                    while True:
                        if self.stop.is_set():raise InterruptedError()
                        finished=owner.proc.poll()
                        chunk=reader.read()
                        if chunk:self.on_ui(lambda text=chunk:self.append_log(text))
                        if finished is not None:break
                        self.stop.wait(.4)
                    if finished:raise RuntimeError(f"Falha em {title}. Registro: {log}")
                    self.on_ui(after)
                finally:
                    owner.close();self.foreground=None
        self._run(title,job)
        self._update_stats()
    def append_log(self,text):
        self.log.insert("end",text.replace("\r","\n"))
        if int(self.log.index("end-1c").split(".")[0])>1200:self.log.delete("1.0","400.0")
        self.log.see("end")
        for line in reversed(text.splitlines()):
            if line.strip():self.status.set(line.strip()[:145]);break
        if self.gallery_ui.dest and self.tabs.select()==self.tabs.aliases[str(self.training_tab)] and self.train_book.select()==str(self.tab_gallery):
            self.gallery_ui.draw()
    def _reject(self):
        self.batch_remove()
    def _close(self):
        if not self.busy:
            self.save_preferences();self.release_caption()
        super()._close()

if __name__=="__main__":
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.CreateMutexW.restype=wintypes.HANDLE
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        handle=kernel.CreateMutexW(None,False,r"Local\HydraTrainer-Desktop")
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:
            messagebox.showinfo("HydraTrainer","O aplicativo já está aberto.");sys.exit()
    else:
        import fcntl
        lock=(DATA/"interface.lock").open("a")
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit("HydraTrainStudio já está aberto.")
    window=Hydra()
    window.mainloop()

