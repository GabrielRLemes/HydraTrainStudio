from copy import deepcopy
import tkinter as tk
from tkinter import ttk,messagebox
from captions import create_caption,create_tags,polish_caption
from revisao import state,selected,field

class Legendas:
    def captions_profile(self,single=False,force=False):
        name=field(self.family.get())
        keys=[self.current_key] if single else list(self.project.items)
        self.run_review_ai(keys,"caption" if name=="krea" else "tags",force)

    def review_ai(self,operation,force=False):
        keys=list(self.tree.selection())
        if not keys:
            messagebox.showinfo("Revisão","Selecione uma ou mais imagens na lista.");return
        self.run_review_ai(keys,operation,force)

    def redo_project(self,operation):
        keys=[k for k,it in self.project.items.items() if selected(it)]
        self.run_review_ai(keys,operation,True,scope="do projeto inteiro")

    def run_review_ai(self,keys,operation,force,scope="da seleção"):

        if self.busy:return
        self._save_edit()
        profile=self.family.get()
        size=int(self.resolution.get())
        name="sdxl" if operation=="tags" else "krea"
        stale="caption_stale" if name=="krea" else "tags_stale"
        manual="caption_edited" if name=="krea" else "sdxl_edited"
        keys=[k for k in keys if k and selected(self.project.items[k]) and (force or
              (not self.project.items[k].get(manual) and (not self.project.items[k].get(name) or self.project.items[k].get(stale))))]
        if not keys:messagebox.showinfo("Legendas","Todas as legendas elegíveis já estão preenchidas. As edições manuais são preservadas.");return
        if force:
            kind="as tags" if name=="sdxl" else "as captions"
            if not messagebox.askyesno("Revisão",f"Refazer {kind} de {len(keys)} item(ns) {scope}? O texto anterior ficará no histórico de cada item."):return
        try:cfg=self._ai_config(name=="krea")
        except Exception as exc:messagebox.showerror("Modelo de caption",str(exc));return
        if cfg.provider in ("Google Gemini","OpenRouter") and not messagebox.askyesno("Provedor externo",f"Enviar {len(keys)} imagens ao provedor {cfg.provider}?"):return
        def work():
            self.progress.plan(len(keys))
            lane="tags" if name=="sdxl" else "caption"
            self.progress.count(lane,"Seleção",planned=len(keys))
            for key in keys:
                if self.stop.is_set():return
                def snapshot():
                    it=deepcopy(self.project.items[key]);it["ai_resolution"]=size
                    return it,self.project.path_for(it)
                it,path=self.on_ui(snapshot)
                geom=state(it,profile,size)
                if name=="krea":
                    captioner=polish_caption if operation=="enhance" else create_caption
                    value=captioner(path,it,cfg)
                else:
                    tags=create_tags(path,it,cfg);value=", ".join(tags)
                def commit():
                    live=self.project.items[key]
                    if self.stop.is_set() or self.family.get()!=profile or int(self.resolution.get())!=size or not selected(live) or state(live,profile,size)!=geom or any(live.get(k)!=it.get(k) for k in ("tags","krea","sdxl")):return
                    if not value.strip():raise ValueError("O modelo retornou texto vazio.")
                    if live.get(name):
                        live.setdefault("historico_hydra",[]).append({name:live[name],"crop":geom["crop"],"res":size})
                    live[name]=value
                    if name=="sdxl":
                        live.update(tags=tags,tags_ready=True,caption_stale=bool(live.get("krea")),tags_geom=["Recortar 1:1",geom["crop"],size])
                    else:live.update(caption_geom=["Recortar 1:1",geom["crop"],size])
                    live.update({stale:False,manual:False,"ai_error":"","status":"pendente"})
                    live.pop("hydra_aprovacao",None)
                    self.project.save_one(key)
                    self.refresh_text(key);self._update_tree(key)
                self.on_ui(commit);self.progress.advance();self.progress.count(lane,"Seleção",done=1)
        self._run("Gerando legendas no enquadramento atual",work,prepare_cfg=cfg)

