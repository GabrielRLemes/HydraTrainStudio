"""Frame controls, project management and inference actions for the Tk studio."""
import json
import csv
import os
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk

from caption_profiles import PROFILE_SDXL
from core import atomic_json
from jobs import run_jobs
from live import tag_received
from media import Settings, PROFILES

QWEN_BAT = Path(__file__).parent / "llama-server.exe"

class Studio:
    def studio_controls(self):
        self.media_filters = {k:tk.BooleanVar(value=True) for k in ("Imagens","GIFs/animações","Vídeos")}
        self.download_ai=tk.BooleanVar(value=True)
        self.process_download = tk.BooleanVar(value=True)
        self.auto_approve = tk.BooleanVar()
        self.import_prepare = tk.BooleanVar()
        self.sidecar = tk.StringVar(value="Ignorar")

        for parent in (self.tab_search,self.tab_import):
            row = self.row(parent)
            first=next(c for c in parent.winfo_children() if isinstance(c,ttk.LabelFrame))
            if parent==self.tab_search:row.pack_configure(after=first)
            else:row.pack_configure(before=first)
            if parent == self.tab_search:
                for key,var in self.media_filters.items():
                    ttk.Checkbutton(row,text=key,variable=var).pack(side="left")
                ttk.Checkbutton(row,text="Processar após baixar (desmarque para só originais)",variable=self.process_download).pack(side="left")
                ttk.Checkbutton(row,text="Gerar tags se o post não tiver tags",variable=self.download_ai).pack(side="left")
            else:
                ttk.Label(row,text="TXT adjacente").pack(side="left")
                self.combo(row,self.sidecar,["Ignorar","Tags","Caption"])
                ttk.Checkbutton(row,text="Preparar automaticamente após importar",variable=self.import_prepare).pack(side="left")
                ttk.Button(row,text="Mapear JSON/CSV",command=self.map_metadata).pack(side="left")

        row=self.row(self.tab_project)
        for label,command in [("Abrir / criar projeto",self._change_workspace),("Backup completo",self.backup),("Índice entre projetos",self.choose_library),
                              ("Novo projeto",self._reset),("Iniciar Qwen local",self.launch_qwen)]:
            ttk.Button(row,text=label,command=command).pack(side="left",padx=4)
        
        self.source_stats=ttk.Label(self.tab_project,justify="left")
        self.source_stats.pack(anchor="w",pady=12)
        row=self.row(self.tab_ai)
        ttk.Label(row,text="Máximo de tokens").pack(side="left")
        ttk.Entry(row,textvariable=self.token_limit,width=8).pack(side="left")
        fields=asdict(self.project.settings)
        self.extract_vars={}
        labels={"profile":"Perfil","interval_ms":"Intervalo (ms)","per_media":"Máx. por mídia",
                "per_scene":"Máx. por cena","sensitivity":"Sensibilidade","min_side":"Lado mínimo (px)",
                "sharpness":"Sinalizar nitidez abaixo de","max_seconds":"Duração máxima (s)","max_mb":"Máx. original (MB)","ffprobe":"FFprobe opcional (caminho)"}
        source=ttk.LabelFrame(self.tab_frames,text="Arquivos de vídeo e GIF",padding=10);source.pack(fill="x",pady=5)
        ttk.Label(source,textvariable=self.workspace_text).pack(anchor="w")
        ttk.Button(source,text="Importar mídias locais",command=self._import_files).pack(anchor="w")
        options=ttk.LabelFrame(self.tab_frames,text="Opções de extração",padding=12);options.pack(fill="x",pady=5)
        preferences=ttk.LabelFrame(self.extract_settings,text="Opções de extração",padding=12);preferences.pack(fill="x",pady=5)
        for key in labels:self.extract_vars[key]=tk.StringVar(value=str(fields[key]))
        flags=(("full_scan","Varredura completa"),("allow_similar","Manter semelhantes"))
        for key,_ in flags:self.extract_vars[key]=tk.BooleanVar(value=fields[key])
        for card in (options,preferences):
            for i,(key,label) in enumerate(labels.items()):
                if i%2==0:row=self.row(card)
                ttk.Label(row,text=label).pack(side="left",padx=4)
                var=self.extract_vars[key]
                if key=="profile":self.combo(row,var,list(PROFILES))
                else:ttk.Entry(row,textvariable=var,width=8).pack(side="left")
            row=self.row(card)
            for key,label in flags:ttk.Checkbutton(row,text=label,variable=self.extract_vars[key]).pack(side="left")
        ttk.Button(preferences,text="Salvar no projeto",command=self.save_project).pack(anchor="e")
        row=self.row(self.tab_frames)
        # A aprovação no HydraTrainer é individual após conferir a prévia.
        ttk.Button(row,text="Extrair frames",command=self.analyze).pack(side="left")
        row=self.row(self.tab_frames)
        for label,status in [("Rejeitar seleção","rejeitado")]:
            ttk.Button(row,text=label,command=lambda st=status:self.frame_status(st)).pack(side="left")
        self.gallery=ttk.Treeview(self.tab_frames,columns=("pts","scene","sharp","sim","status"),height=10)
        for col,label in [("#0","Arquivo / frame"),("pts","PTS (ms)"),("scene","Cena"),("sharp","Nitidez"),("sim","Semelhança"),("status","Estado")]:
            self.gallery.heading(col,text=label)
            self.gallery.column(col,width=260 if col=="#0" else 75)
        self.gallery.pack(fill="both",expand=True)
        self.gallery.bind("<<TreeviewSelect>>",self.compare)
        self.gallery.bind("<Map>",lambda _:self.refresh_gallery() if getattr(self,"gallery_dirty",False) else None)
        self.previews=ttk.Label(self.tab_frames)
        self.previews.pack()
        self.refresh_gallery()
        self.fit_mode.trace_add("write",self.geometry_changed)
        self.resolution.trace_add("write",self.geometry_changed)

    def geometry_changed(self,*_):
        if self.busy and not self.editable_job:return
        for it in self.project.items.copy().values():
            geom=[self.fit_mode.get(),it["crop"],int(self.resolution.get())]
            if it.get("tags_geom") and it["tags_geom"]!=geom:it["tags_stale"]=True
            if it.get("caption_geom") and it["caption_geom"]!=geom:it["caption_stale"]=True
        self.project.save()
        self._draw()

    @staticmethod
    def combo(row,var,values):
        ttk.Combobox(row,textvariable=var,values=values,state="readonly",width=max(15,max(map(len,values)))).pack(side="left",padx=4)

    def sync_options(self):
        defaults=asdict(Settings())
        cfg=Settings(**{k:type(defaults[k])(v.get()) for k,v in self.extract_vars.items()})
        cfg.validate()
        self.project.settings=cfg
        self.project.persist_options()
        self.project.stop=self.stop
        self.project.sidecar_mode=self.sidecar.get()

    def refresh_gallery(self):
        from collections import Counter,defaultdict
        media=list(self.project.db.execute("SELECT id,filename,kind,origins FROM media ORDER BY rowid"))
        visible=self.gallery.winfo_ismapped()
        self.gallery_dirty=not visible
        if visible:
            self.gallery.delete(*self.gallery.get_children())
            for parent in media:self.gallery.insert("","end",iid=parent["id"],text=parent["filename"],open=True)
        by_parent=defaultdict(Counter)
        for key,it in self.project.items.copy().items():
            counts=by_parent[it["media_uid"]]
            counts["frames"]+=it.get("frame_index") is not None
            counts["aprovados"]+=it["status"]=="aprovado"
            counts["duplicados"]+=it["status"]=="duplicado"
            if visible and not it.get("removed"):
                self.gallery.insert(it["media_uid"],"end",iid=key,text=it["filename"],values=[
                    it.get("pts_ms"),it.get("scene",""),it.get("sharpness",""),it.get("similarity",""),it["status"]])
        summary=defaultdict(Counter)
        for parent in media:
            for source in {o["source"] for o in json.loads(parent["origins"])}:
                summary[source][parent["kind"]]+=1
                summary[source].update(by_parent[parent["id"]])
        self.source_stats.configure(text="\n".join(f"{src}: "+", ".join(f"{k} {v}" for k,v in counts.items()) for src,counts in summary.items()))

    def compare(self,_=None):
        keys=[k for k in self.gallery.selection() if k in self.project.items][:2]
        preview=Image.new("RGB",(460,130),"#273041")
        for i,k in enumerate(keys):
            p=self.project.path_for(self.project.items[k])
            if p.exists():
                with Image.open(p) as im:
                    im.thumbnail((225,130))
                    preview.paste(im,(230*i,0))
        self.preview_photo=ImageTk.PhotoImage(preview)
        self.previews.configure(image=self.preview_photo)

    def frame_status(self,status):
        if self.busy:return
        for k in self.gallery.selection():
            for key in ([k] if k in self.project.items else self.project.children(k)):
                if self.project.items[key].get("removed"):continue
                self.project.items[key]["status"]=status
                self.project.save_one(key)
        self.refresh_gallery()
        self._refresh_tree()

    def prepare_callback(self,enabled,download=False):
        approve=self.auto_approve.get()
        cfg=None
        if enabled and self.provider.get()!="Nenhuma":
            cfg=self._ai_config(False)
            if cfg.provider in ("Google Gemini","OpenRouter") and not messagebox.askyesno("API externa","Enviar imagens sem tags ao provedor externo para gerar tags?"):
                raise ValueError("Envio cancelado.")
        seen=set()
        def received(key):
            if key in seen or self.stop.is_set():return
            seen.add(key)
            item=self.project.items[key]
            if item.get("removed"):return
            if approve and item["status"]=="pendente" and not item.get("uncertain"):
                item["status"]="aprovado"
                self.project.save_one(key)
            self.events.put(("new_item",key,item["filename"]+" · disponível para revisão"))
            if item.get("inherited_tags"):
                self.progress.count("tags","Tags do post",planned=1,done=1)
            if cfg and item["status"] in ("pendente","aprovado") and not item.get("tags") and not item.get("sdxl_edited"):
                self.progress.count("tags","Imagens sem tags",planned=1)
                self.pending_ai.append(self.ai_worker.submit(tag_received,self,key,cfg))
        self.project.frame_received=received
        def prepare(key):
            for child in self.project.children(key):received(child)
            if cfg:
                self.pending_ai.append(self.ai_worker.submit(lambda:None if self.stop.is_set() else self.progress.advance()))
            else:self.progress.advance()
        prepare.ai_config=cfg
        return prepare

    def ready_media(self,key):
        keys=self.project.children(key)
        if self.auto_approve.get():
            for k in keys:
                it=self.project.items[k]
                if it["status"]=="pendente" and not it.get("uncertain"):
                    it["status"]="aprovado"
                    self.project.save_one(k)
        return keys

    def analyze(self):
        if self.busy:return
        try:self.sync_options()
        except Exception as e:messagebox.showerror("Extrator",str(e));return
        def task():
            parents=self.project.db.execute("SELECT id FROM media").fetchall()
            self.progress.plan(len(parents))
            for (parent,) in parents:
                if self.stop.is_set():break
                self.project.extract(parent)
                self.ready_media(parent)
                self.progress.advance()
        self.project.frame_received=lambda key:self.events.put(("new_item",key,"Frame disponível para revisão"))
        self._run("Analisando originais",task,editable=True)

    def ai_queue(self,operation,selected=False,force=False):
        if self.busy:
            messagebox.showinfo("Descrição","Aguarde a tarefa atual terminar para iniciar outro lote.")
            return
        self._save_edit()
        keys=[self.current_key] if selected and self.current_key else list(self.project.items) if not selected else []
        keys=[k for k in keys if self.project.items[k]["status"] in ("pendente","aprovado") and not self.project.items[k].get("removed")]
        if operation=="caption" and not force:
            keys=[k for k in keys if not self.project.items[k].get("krea")]
        if operation=="tags":
            keys=[k for k in keys if not self.project.items[k].get("tags") and not self.project.items[k].get("sdxl_edited")]
        if not keys:
            messagebox.showinfo("IA","Nenhuma imagem da lista precisa desta operação.");return
        try:cfg=self._ai_config(operation!="tags")
        except Exception as exc:messagebox.showerror("IA",str(exc));return
        if force or cfg.provider in ("Google Gemini","OpenRouter"):
            if not messagebox.askyesno("Confirmar IA",f"{cfg.provider}: processar {len(keys)} imagens? Regeneração substitui as edições após backup."):return
        if force:
            atomic_json(self.project.root/"backups"/(datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".json"),{k:self.project.items[k] for k in keys})
        for k in keys:self.project.items[k]["ai_resolution"]=int(self.resolution.get())
        fit,profile=self.fit_mode.get(),self.profile.get()
        def task():
            self.progress.plan(len(keys))
            failed=0
            missing={k for k in keys if not self.project.items[k].get("tags") and not self.project.items[k].get("sdxl_edited")}
            if missing:self.progress.count("tags","Imagens sem tags",planned=len(missing))
            if operation!="tags":self.progress.count("caption","Descrições",planned=len(keys))
            for key in keys:
                if self.stop.is_set():break
                notify=lambda k,msg:self.events.put(("notice",msg+" · "+self.project.items[k]["filename"]))
                error=0
                if key in missing:
                    error=run_jobs(self.project,[key],"tags",cfg,profile,fit,self.stop,notify,allow_pending=True)
                    self.progress.count("tags","Imagens sem tags",done=1)
                if operation!="tags":
                    if not error:
                        error=run_jobs(self.project,[key],"caption",cfg,profile,fit,self.stop,notify,force=force,allow_pending=True)
                    self.progress.count("caption","Descrições",done=1)
                failed+=error
                self.progress.advance()
            self.events.put(("notice",f"Fila encerrada. Falhas: {failed}"))
        self._run("Processando lista",task,prepare_cfg=cfg)

    def choose_library(self):
        if self.busy:return
        dest=filedialog.askdirectory(title="Biblioteca compartilhada por estes projetos")
        if dest:self._run("Indexando projeto",lambda:self.project.configure_library(dest))

    def backup(self):
        if self.busy:return
        target=filedialog.asksaveasfilename(defaultextension=".zip",filetypes=[("Backup ZIP","*.zip")])
        if not target:return
        def task():
            import sqlite3
            import tempfile
            with tempfile.TemporaryDirectory() as temp:
                dbpath=Path(temp)/"catalogo.sqlite"
                db=sqlite3.connect(dbpath)
                try:self.project.db.backup(db)
                finally:db.close()
                with ZipFile(target,"w") as archive:
                    archive.write(dbpath,"catalogo.sqlite")
                    for folder in (self.project.images,self.project.cache):
                        if self.project.config_path.is_file() and self.project.config_path.name not in archive.namelist():archive.write(self.project.config_path,self.project.config_path.name)
                        for path in folder.iterdir():
                            if path.is_file():archive.write(path,path.relative_to(self.project.root))
        self._run("Criando backup",task)

    def launch_qwen(self):
        if QWEN_BAT.is_file():os.startfile(QWEN_BAT)
        else:messagebox.showerror("Qwen","Lançador ausente: "+str(QWEN_BAT))

    def map_metadata(self):
        if self.busy:return
        path=filedialog.askopenfilename(filetypes=[("Metadados","*.json *.csv")])
        if not path:return
        names=simpledialog.askstring("Mapeamento","Colunas para caminho, tags e caption (separadas por vírgula):",initialvalue="path,tags,caption")
        if not names:return
        try:
            media_field,tags_field,cap_field=[s.strip() for s in names.split(",")]
            p=Path(path)
            with p.open(encoding="utf-8-sig",newline="") as f:
                rows=json.load(f) if p.suffix.lower()==".json" else list(csv.DictReader(f))
            if not isinstance(rows,list):raise ValueError("Esperada uma lista de registros.")
            from sources import Post,canonical_tags
            self.sync_options()
            def task():
                self.progress.plan(len(rows))
                for row in rows:
                    if self.stop.is_set():break
                    src=(p.parent/row[media_field]).resolve()
                    raw=row.get(tags_field) or []
                    tags=canonical_tags(raw.split(",") if isinstance(raw,str) else raw)
                    post=Post("Local",str(src),"","",tags,metadata={"sidecar_caption":row.get(cap_field)})
                    self.project.receive(src,"Local",str(src),post=post)
                    self.progress.advance()
            self._run("Importando metadados",task)
        except Exception as exc:messagebox.showerror("Mapeamento",str(exc))

