from tkinter import ttk
import tkinter as tk
import math

# key, label, default, type, limits or choices
FIELDS=(
 ("epochs","Épocas (0 = usar passos)",0,int,(0,100000)),
 ("rank","Rank do LoRA",16,int,(1,1024)),
 ("alpha","Alpha do LoRA",16,float,(0.001,1024)),
 ("batch","Lote por dispositivo",1,int,(1,128)),
 ("accum","Acumulação de gradiente",1,int,(1,1024)),
 ("optimizer","Otimizador","AdamW8bit",str,("AdamW8bit","AdamW")),
 ("scheduler","Agenda de aprendizado","constant",str,("constant","constant_with_warmup","linear","cosine")),
 ("warmup","Passos de aquecimento",0,int,(0,10000000)),
 ("clip","Norma máxima do gradiente",1,float,(0,10000)),
 ("seed","Semente",42,int,(0,4294967295)),
 ("workers","Workers de dados",0,int,(0,32)),
 ("save","Precisão do arquivo","bf16",str,("bf16","fp16","float")),
 ("checkpoint","Checkpoint de gradiente",True,bool,()),
)

def target_steps(opt,steps,count):
    if opt["epochs"] and count:
        batches=math.ceil(count/opt["batch"])
        return opt["epochs"]*math.ceil(batches/opt["accum"])
    return steps

def options(values,steps,count):
    result={}
    for key,label,default,kind,limits in FIELDS:
        raw=values.get(key,default)
        try:
            if kind is bool:
                if not isinstance(raw,bool):raise ValueError()
                value=raw
            elif kind is str:
                if raw not in limits:raise ValueError()
                value=raw
            else:
                value=kind(str(raw).replace(",","."))
                if not math.isfinite(value) or not limits[0]<=value<=limits[1]:raise ValueError()
        except (TypeError,ValueError,OverflowError):
            raise ValueError(f"{label}: valor inválido ({raw}).")
        result[key]=value
    if result["warmup"]>target_steps(result,steps,count) or (result["warmup"] and result["scheduler"]=="constant"):
        raise ValueError("Aquecimento requer uma agenda compatível e não pode exceder os passos.")
    return result

def controls(app,parent):
    app.advanced_mode=tk.BooleanVar(value=False)
    row=ttk.Frame(parent);row.pack(fill="x")
    panel=ttk.Frame(parent)
    app.advanced_vars={}
    def toggle():
        if app.advanced_mode.get():panel.pack(fill="x")
        else:panel.pack_forget()
        app._update_stats()
        app.after_idle(lambda:app.training_tab.master.event_generate("<Configure>"))
    for label,value in (("Automático",False),("Avançado",True)):
        ttk.Radiobutton(row,text=label,value=value,variable=app.advanced_mode,command=toggle).pack(side="left",padx=4)
    for key,label,default,kind,limits in FIELDS:
        var=tk.BooleanVar(value=default) if kind is bool else tk.StringVar(value=str(default))
        app.advanced_vars[key]=var
        if kind is bool:ttk.Checkbutton(panel,text=label,variable=var).pack(anchor="w")
        elif kind is str:
            r=app.row(panel);ttk.Label(r,text=label,width=25).pack(side="left")
            ttk.Combobox(r,textvariable=var,values=limits,state="readonly").pack(side="left")
        else:app.field(panel,label,var)
        var.trace_add("write",lambda *_:app._update_stats())
    ttk.Label(panel,text="A calibração de memória usa os parâmetros automáticos.",wraplength=340).pack(anchor="w")
