import base64
import ctypes
from ctypes import wintypes
import json
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from configuracao import DATA, read_json, write_json
from caption_profiles import PROFILE_ORDER, PROFILE_CUSTOM, PROFILE_DETAILED, get_profile_prompt

FILE=DATA/"interface.json"
CREDENTIALS=("username","e621_key","dan_user","dan_key","gel_id","gel_key","rule_id","rule_key","derpi_key")

class Blob(ctypes.Structure):
    _fields_=[("size",wintypes.DWORD),("data",ctypes.c_void_p)]

def protect(value,decode=False):
    import os
    if os.name!="nt":
        from keyring.backends.SecretService import Keyring
        try:
            ring=Keyring()
            if decode:
                if value!="secret-service":raise ValueError("Formato de credencial incompatível.")
                return ring.get_password("HydraTrainStudio",str(DATA)) or "{}"
            ring.set_password("HydraTrainStudio",str(DATA),value)
            return "secret-service"
        except Exception as exc:raise ValueError("Chaveiro Secret Service indisponível.") from exc
    raw=base64.b64decode(value) if decode else value.encode("utf-8")
    buf=ctypes.create_string_buffer(raw)
    src=Blob(len(raw),ctypes.cast(buf,ctypes.c_void_p));out=Blob()
    dll=ctypes.WinDLL("crypt32",use_last_error=True)
    fn=dll.CryptUnprotectData if decode else dll.CryptProtectData
    if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result=ctypes.string_at(out.data,out.size)
        return result.decode("utf-8") if decode else base64.b64encode(result).decode("ascii")
    finally:
        free=ctypes.windll.kernel32.LocalFree
        free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        free(out.data)

class Preferences:
    def init_preferences(self):
        self.settings=read_json(FILE,{})
        self.saving=False;self.pending_save=None
        self.e621_key=tk.StringVar();self.dan_user=tk.StringVar();self.dan_key=tk.StringVar()
        self.secrets={}
        encrypted=self.settings.get("contas")
        self.locked_accounts=False
        if encrypted:
            try:self.secrets=json.loads(protect(encrypted,True))
            except (OSError,ValueError):
                self.locked_accounts=True
                self.status.set("As credenciais salvas pertencem a outra sessão do Windows. Use Redefinir credenciais para substituí-las.")
        for k in CREDENTIALS:getattr(self,k).set(self.secrets.get(k,""))
        self.provider.set(self.settings.get("provedor",self.provider.get()))
        self.active_provider=self.provider.get()
        self.trigger.set(self.settings.get("trigger",self.trigger.get()))
        self.vision_think=tk.BooleanVar(value=self.settings.get("vision_think",bool(self.cfg.get("modelo_think") and self.cfg.get("projetor_think"))))
        self.token_limit=tk.StringVar(value=str(self.settings.get("tokens","550")))
        self.theme=tk.StringVar(value=self.settings.get("tema","Escuro"))
        self.font_size=tk.IntVar(value=self.settings.get("fonte",10))
        self.prompts=dict(self.settings.get("prompts",{}))
        self.load_provider()
    def load_provider(self):
        name=self.active_provider
        default={"llama.cpp (local)":("http://127.0.0.1:8080","qwen3vl-8b-abliterated"),"Ollama (local)":("http://127.0.0.1:11434","")}
        url,model=default.get(name,("",""))
        rec=self.settings.get("servicos",{}).get(name,{})
        self.api_url.set(rec.get("url",url));self.model.set(rec.get("modelo",model))
        self.api_key.set(self.secrets.get("ia",{}).get(name,""))
    def remember_provider(self):
        if not self.caption_process:
            self.settings.setdefault("servicos",{})[self.active_provider]={"url":self.api_url.get(),"modelo":self.model.get()}
        self.secrets.setdefault("ia",{})[self.active_provider]=self.api_key.get()
    def provider_changed(self,_=None):
        if self.busy:
            self.provider.set(self.active_provider);return
        self.remember_provider();self.release_caption()
        self.active_provider=self.provider.get();self.load_provider();self.save_preferences()
    def watch_preferences(self):
        self.saving=True
        variables=[getattr(self,k) for k in CREDENTIALS]+[self.api_url,self.model,self.api_key,self.trigger,self.token_limit,self.theme,self.font_size,self.vision_think]
        for var in variables:var.trace_add("write",lambda *_:self.queue_save())
    def queue_save(self):
        if not self.saving:return
        if self.pending_save:self.after_cancel(self.pending_save)
        self.pending_save=self.after(450,self.save_preferences)
    def save_preferences(self):
        if self.pending_save:self.after_cancel(self.pending_save);self.pending_save=None
        self.remember_provider()
        self.settings.update(provedor=self.active_provider,trigger=self.trigger.get(),tokens=self.token_limit.get(),vision_think=self.vision_think.get(),
                             tema=self.theme.get(),fonte=self.font_size.get(),prompts=self.prompts,perfil_prompt=self.profile.get())
        if not self.locked_accounts:
            self.secrets.update({k:getattr(self,k).get() for k in CREDENTIALS})
            # A fresh Linux installation needs no keyring until the user saves a credential.
            has_keys=any(value for key,value in self.secrets.items() if key!="ia") or any(self.secrets.get("ia",{}).values())
            try:
                if has_keys or self.settings.get("contas"):
                    self.settings["contas"]=protect(json.dumps(self.secrets,ensure_ascii=False))
            except ValueError:self.status.set("Chaveiro indisponível. Credenciais somente nesta sessão.")
        write_json(FILE,self.settings)
    def reset_accounts(self):
        if not messagebox.askyesno("Credenciais","Limpar as contas e chaves de API salvas neste HydraTrainer?"):return
        self.secrets={};self.locked_accounts=False
        for k in CREDENTIALS:getattr(self,k).set("")
        self.api_key.set("");self.save_preferences()
    def load_prompts(self):
        legacy=self.project.root/"prompt_personalizado.txt"
        has_legacy=legacy.is_file() and self.project.root.name not in self.settings.get("legados_renomeados",[])
        if has_legacy:
            label="Personalizado · "+self.project.root.name
            if label not in self.prompts:self.prompts[label]=legacy.read_text("utf-8-sig").strip()
        self.prompt_names=[v for v in PROFILE_ORDER if v!=PROFILE_CUSTOM]+list(self.prompts)
        self.prompt_box.configure(values=self.prompt_names)
        choice=self.settings.get("perfil_prompt")
        if choice not in self.prompt_names:choice=label if has_legacy else PROFILE_DETAILED
        self.profile.set(choice);self.show_prompt()
    def show_prompt(self,event=None):
        name=self.profile.get()
        text=self.prompts[name] if name in self.prompts else get_profile_prompt(name)
        self.prompt.configure(state="normal");self.prompt.delete("1.0","end");self.prompt.insert("1.0",text)
        self.prompt.edit_modified(False)
        if name not in self.prompts:self.prompt.configure(state="disabled")
        if self.saving:self.save_preferences()
    def edit_prompt(self,_=None):
        if not self.prompt.edit_modified():return
        self.prompt.edit_modified(False)
        if self.profile.get() in self.prompts:
            self.prompts[self.profile.get()]=self.prompt.get("1.0","end-1c");self.queue_save()
    def named_prompt(self,rename=False):
        old=self.profile.get()
        if rename and old not in self.prompts:
            messagebox.showinfo("Prompts","Crie uma cópia para editar este prompt predefinido.");return
        name=simpledialog.askstring("Prompts","Nome do prompt",initialvalue=old if rename else "")
        if not name or not (name:=name.strip()):return
        if name==old and rename:return
        if name in self.prompt_names or name==PROFILE_CUSTOM:
            messagebox.showerror("Prompts","Esse nome já está em uso.");return
        self.prompts[name]=self.prompt.get("1.0","end-1c")
        if rename:del self.prompts[old]
        self.settings["perfil_prompt"]=name
        # Do not recreate a renamed legacy prompt on the next launch.
        if rename and old=="Personalizado · "+self.project.root.name:
            self.settings.setdefault("legados_renomeados",[]).append(self.project.root.name)
        self.load_prompts();self.save_preferences()

def apply_style(app):
    dark=app.theme.get()=="Escuro"
    bg,field,fg,muted,accent=("#161924","#191C28","#F1F1FA","#B6B8CD","#974BDD") if dark else ("#f2f4f6","#ffffff","#172333","#435266","#275e85")
    size=app.font_size.get()
    st=ttk.Style(app)
    st.configure(".",background=bg,foreground=fg,font=("Segoe UI",size),fieldbackground=field)
    card="#1D2030" if dark else "#ffffff"
    border="#414456" if dark else "#bec6cf"
    sidebar="#171A28" if dark else "#e7ebef"
    header="#161824" if dark else "#eef1f4"
    st.configure(".",bordercolor=border,lightcolor=border,darkcolor=border)
    st.configure("Header.TFrame",background=header)
    st.configure("Header.TLabel",background=header)
    st.configure("Sidebar.TFrame",background=sidebar)
    st.configure("Tile.TFrame",background=card,bordercolor=border,borderwidth=1,relief="solid")
    st.configure("Tile.TLabel",background=card,foreground=muted,font=("Segoe UI",max(9,size-1)))
    st.configure("TileTitle.TLabel",background=card,font=("Segoe UI",size,"bold"))
    for name in ("Tile.TFrame","Tile.TLabel","TileTitle.TLabel"):
        st.configure("Hover."+name,background="#292D40" if dark else "#e3e8ef")
    st.configure("Metric.TLabel",font=("Segoe UI",size+2,"bold"))
    st.configure("TNotebook.Tab",padding=(12,8))
    st.layout("Studio.TNotebook.Tab",[])
    st.configure("Studio.TNotebook",tabmargins=0,borderwidth=0)
    st.configure("Nav.TButton",padding=(10,11),anchor="w",font=("Segoe UI",11),background=sidebar,borderwidth=0)
    st.configure("NavActive.TButton",padding=(10,11),anchor="w",font=("Segoe UI",11),borderwidth=0,background="#49357D",foreground="#F0F1F5")
    st.map("NavActive.TButton",background=[("active","#5E3B9C")])
    st.configure("PageTitle.TLabel",font=("Segoe UI",18,"bold"),foreground=fg)
    st.configure("Secondary.TLabel",foreground=muted)
    st.configure("TButton",padding=(9,7),borderwidth=1)
    st.configure("TLabelframe",background=card,borderwidth=1,relief="solid");st.configure("TLabelframe.Label",background=card,font=("Segoe UI",size+1,"bold"))
    st.map("TButton",foreground=[("disabled","#737B8C")])
    st.configure("TScrollbar",background=border,troughcolor=bg,arrowcolor=muted)
    st.configure("TProgressbar",background=accent,troughcolor=field)
    st.configure("Card.TLabel",background=card)
    st.configure("Card.TFrame",background=card)
    st.configure("TEntry",padding=6)
    st.configure("TCombobox",padding=5)
    st.map("TNotebook.Tab",background=[("selected",accent)],foreground=[("selected","#ffffff")])
    st.configure("Treeview",background=field,fieldbackground=field,foreground=fg,rowheight=size+15)
    st.map("Treeview",background=[("selected",accent)],foreground=[("selected","white")])
    for name in ("TCombobox","TEntry"):
        st.map(name,fieldbackground=[("readonly",field)],foreground=[("readonly",fg)])
    st.map("TButton",background=[("active",accent)],foreground=[("active","white")])
    st.configure("Primary.TButton",background=accent,foreground="white",padding=(14,10),font=("Segoe UI",size,"bold"))
    st.map("Primary.TButton",background=[("disabled",card),("active","#5E3B9C")],foreground=[("disabled",muted)])
    app.configure(bg="#11131E" if dark else bg)
    app.option_add("*TCombobox*Listbox.background",field)
    app.option_add("*TCombobox*Listbox.foreground",fg)
    def visit(widget,in_card=False):
        in_card=in_card or isinstance(widget,ttk.LabelFrame)
        if in_card and isinstance(widget,(ttk.Label,ttk.Frame)) and not widget.cget("style"):
            widget.configure(style="Card.TLabel" if isinstance(widget,ttk.Label) else "Card.TFrame")
        if isinstance(widget,tk.Text):
            widget.configure(background=field,foreground=fg,insertbackground=fg,selectbackground=accent,font=("Segoe UI",size))
        elif isinstance(widget,tk.Canvas) and widget is not getattr(app,"canvas",None):widget.configure(background=bg)
        elif isinstance(widget,ttk.Label):
            if widget.cget("foreground"):widget.configure(foreground=muted)
            if widget.cget("font") and widget.cget("style")!="PageTitle.TLabel":
                widget.configure(font=("Segoe UI",size+1,"bold"))
        widget.event_generate("<<ResizeRows>>")
        for child in widget.winfo_children():visit(child,in_card)
    visit(app)
    if hasattr(app,"tabs") and hasattr(app.tabs,"changed"):app.tabs.changed()

