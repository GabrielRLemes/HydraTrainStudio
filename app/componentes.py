"""Instalador de componentes opcionais para Windows x64."""
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
from pathlib import Path
from zipfile import ZipFile
from configuracao import ROOT,DATA,CONF,discover,write_json,read_json

from platform_paths import WINDOWS,VENV_PY

ASSETS=read_json(Path(__file__).with_name("arquivos.json"))
COMP=ROOT/"componentes"
CACHE=DATA/"downloads"
TRAIN_COMMIT="372bc94bf8d90f3379b445bc08250b4a2af29af2"
COMFY_COMMIT="63be2f9b82ad0dac88a7ceaa28a9cf3154125a18"
FAMILIES=("Krea2","Anima","Illustrious")
def fetch(url,file,sha=None):
    file.parent.mkdir(parents=True,exist_ok=True)
    if file.is_file():
        if sha:
            with file.open("rb") as f:
                if hashlib.file_digest(f,"sha256").hexdigest()!=sha:raise RuntimeError(f"Hash inválido: {file}")
        return file
    part=file.with_suffix(file.suffix+".part")
    subprocess.run(["curl.exe" if WINDOWS else "curl","-fLsS","--retry","4","--connect-timeout","20","-C","-","-o",str(part),url],check=True)
    if sha:
        with part.open("rb") as f:
            valid=hashlib.file_digest(f,"sha256").hexdigest()==sha
        if not valid:
            invalid=part.with_suffix(".invalido")
            part.replace(invalid)
            raise RuntimeError(f"Hash inválido. Arquivo separado para diagnóstico: {invalid}. Tente novamente.")
    part.replace(file)
    return file

def source(repo,commit,dest):
    marker=dest/".hydra-commit"
    if marker.is_file() and marker.read_text().strip()==commit:return
    if dest.exists():raise RuntimeError(f"Já existe uma instalação diferente em {dest}. Utilize a aba Ambiente.")
    archive=fetch(f"https://codeload.github.com/{repo}/zip/{commit}",CACHE/(commit+".zip"))
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        with ZipFile(archive) as z:z.extractall(tmp)
        folder,=Path(tmp).iterdir()
        (folder/".hydra-commit").write_text(commit)
        folder.rename(dest)

def runner(cmd,**kwargs):
    env={**os.environ,"UV_CACHE_DIR":str(DATA/"cache/uv"),"UV_PYTHON_INSTALL_DIR":str(COMP/"python"),"PYTHONUTF8":"1"}
    subprocess.run(list(map(str,cmd)),check=True,env={**env,**kwargs.pop("env",{})},**kwargs)

def uv():
    if not WINDOWS:
        local=Path(sys.executable).with_name("uv")
        tool=str(local) if local.is_file() else shutil.which("uv")
        if not tool:raise RuntimeError("Abra o aplicativo pelo launcher Linux para instalar uv.")
        return tool
    local=COMP/"uv/uv.exe"
    if local.is_file():return local
    if installed:=shutil.which("uv"):return installed
    asset=next(a for a in ASSETS if a["name"].startswith("uv-"))
    archive=fetch(asset["url"],CACHE/asset["name"],asset["sha"])
    with ZipFile(archive) as z:
        member=next(v for v in z.namelist() if Path(v).name=="uv.exe")
        local.parent.mkdir(parents=True,exist_ok=True)
        local.write_bytes(z.read(member))
    return local

def install_env(dest,torch,vision,req,extra):
    py=dest/VENV_PY;tool=uv()
    if not py.is_file():runner([tool,"venv",dest,"--python","3.12","--managed-python"])
    runner([tool,"pip","install","--python",py,"torch=="+torch+"+cu130","torchvision=="+vision+"+cu130",
            "--index-url","https://download.pytorch.org/whl/cu130","--extra-index-url","https://pypi.org/simple","--index-strategy","unsafe-best-match"])
    runner([tool,"pip","install","--python",py,"-r",req,*extra])
    return py

def wanted(asset,choices):
    n=asset["name"]
    if not WINDOWS and n.endswith(".zip"):return False
    if n.endswith(".gguf") or "llama" in n:return "Caption" in choices
    if n.startswith("uv-"):return False
    if "krea2" in n or "qwen3vl_4b" in n:return "Krea2" in choices
    if "anima-" in n or "qwen_3_06b" in n:return "Anima" in choices
    if n.startswith("vae/"):return "Anima" in choices or "Krea2" in choices
    return "Illustrious" in choices

def reusable(a,cfg):
    n=a["name"]
    if n.endswith(".gguf"):
        key="projetor" if "mmproj" in n else "modelo_caption"
        return Path(cfg.get(key,"")).is_file()
    if n.endswith(".zip"):
        return Path(cfg.get("servidor","")).is_file()
    return any(f.is_file() and f.stat().st_size==a["size"] for f in (Path(cfg["modelos"])/n,COMP/"pesos"/n))

def custom_asset(url,suffix):
    from urllib.parse import urlsplit,unquote
    parsed=urlsplit(url)
    name=Path(unquote(parsed.path)).name
    if (parsed.scheme!="https" or parsed.hostname!="huggingface.co" or "/resolve/" not in parsed.path
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not name.lower().endswith(suffix) or any(c in name for c in '<>:"/\\|?*')):
        raise ValueError("Use um link HTTPS direto do Hugging Face com /resolve/ e extensão "+suffix+".")
    key=hashlib.sha256(url.encode()).hexdigest()[:16]
    return COMP/"selecionados"/key/name

def install(choices):
    cfg=discover()
    if "Caption" in choices and cfg.get("llm_download"):
        for key,url in cfg["llm_download"].items():
            cfg[key]=str(fetch(url,custom_asset(url,".gguf")))
    if "Base de teste" in choices:
        url=cfg.get("teste_download","")
        cfg["ultima_base_teste"]=str(fetch(url,custom_asset(url,".safetensors")))
    library=Path(cfg["treino"])
    py=library/"trainer/venv"/VENV_PY
    has_training=bool(set(FAMILIES)&set(choices))
    managed_train=library.resolve()==(COMP/"treino").resolve()
    if has_training and (not py.is_file() or managed_train and not (library/".pronto").is_file()):
        library=COMP/"treino";trainer=library/"trainer"
        source("amenorira/lora-scripts-anima",TRAIN_COMMIT,trainer)
        py=install_env(trainer/"venv","2.12.1","0.27.1",trainer/"requirements.txt",(["triton-windows>=3.7,<3.8"] if WINDOWS else [])+["pip"])
        (library/".pronto").write_text(TRAIN_COMMIT)
        cfg["treino"]=str(library)
    managed_comfy=Path(cfg["comfy"]).resolve()==(COMP/"Comfy").resolve()
    if "ComfyUI" in choices and (not (Path(cfg["python_comfy"]).is_file() and (Path(cfg["comfy"])/"ComfyUI/main.py").is_file()) or managed_comfy and not (COMP/"Comfy/.pronto").is_file()):
        base=COMP/"Comfy";src=base/"ComfyUI"
        source("comfyanonymous/ComfyUI",COMFY_COMMIT,src)
        cp=install_env(base/"scripts/venv","2.13.0","0.28.0",src/"requirements.txt",[])
        (base/".pronto").write_text(COMFY_COMMIT)
        cfg.update(comfy=str(base),python_comfy=str(cp))
    for a in ASSETS:
        if not wanted(a,choices) or reusable(a,cfg):continue
        n=a["name"]
        if n.endswith(".gguf") and cfg.get("llm_download"):continue
        if n.endswith(".gguf"):
            dest=fetch(a["url"],COMP/"caption"/n,a["sha"])
            cfg["projetor" if "mmproj" in n else "modelo_caption"]=str(dest)
        elif n.endswith(".zip"):
            path=fetch(a["url"],CACHE/n,a["sha"])
            with ZipFile(path) as z:
                for item in z.infolist():
                    if item.is_dir():continue
                    output=COMP/"caption/bin"/Path(item.filename).name
                    output.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(item) as src,output.open("wb") as dst:shutil.copyfileobj(src,dst)
        else:
            fetch(a["url"],COMP/"pesos"/n,a["sha"])
    if not WINDOWS and "Caption" in choices and not Path(cfg.get("servidor","")).is_file():
        existing=shutil.which("llama-server")
        if existing:cfg["servidor"]=existing
        else:
            src=COMP/"llama.cpp"
            source("ggml-org/llama.cpp","b11900",src)
            build=src/"build"
            runner(["cmake","-S",src,"-B",build,"-DCMAKE_BUILD_TYPE=Release","-DGGML_CUDA="+("ON" if shutil.which("nvcc") else "OFF"),"-DLLAMA_CURL=OFF"])
            runner(["cmake","--build",build,"--target","llama-server","-j","2"])
            cfg["servidor"]=str(build/"bin/llama-server")
    if not Path(cfg.get("servidor","")).is_file() and (COMP/"caption/bin/llama-server.exe").is_file():
        cfg["servidor"]=str(COMP/"caption/bin/llama-server.exe")
    if not Path(cfg["modelos"]).is_dir():cfg["modelos"]=str(COMP/"pesos")
    if has_training:
        # A private tokenizer cache is prepared only for a new, Hydra-managed installation.
        if library.resolve()==(COMP/"treino").resolve():
            repos=[]
            if "Krea2" in choices:repos.append("Qwen/Qwen3-VL-4B-Instruct")
            if "Illustrious" in choices:repos.extend(["openai/clip-vit-large-patch14","laion/CLIP-ViT-bigG-14-laion2B-39B-b160k"])
            code="from huggingface_hub import snapshot_download; import sys; [snapshot_download(r,allow_patterns=['tokenizer*','*vocab*','*merges*','*special_tokens*','config.json','*chat_template*']) for r in sys.argv[1:]]"
            runner([py,"-c",code,*repos],env={"HF_HOME":str(library/"cache/huggingface"),"HF_HUB_OFFLINE":"0"})
    write_json(CONF,cfg)

def wizard():
    win=tk.Tk();win.title("HydraTrainer · componentes");win.geometry("770x620")
    cfg=discover();frame=ttk.Frame(win,padding=18);frame.pack(fill="both",expand=True)
    ttk.Label(frame,text="Escolha o que instalar",font=("Segoe UI",16,"bold")).pack(anchor="w")
    options={k:tk.BooleanVar() for k in (*FAMILIES,"Caption","ComfyUI","Base de teste")}
    info=tk.StringVar()
    def refresh():
        choices=[k for k,v in options.items() if v.get()]
        assets=[a for a in ASSETS if wanted(a,choices)]
        size=sum(a["size"] for a in assets if not reusable(a,cfg))
        info.set(f"Arquivos de modelo e llama.cpp a baixar: {size/1e9:.2f} GB (modelos por URL são adicionais).\nReserve aproximadamente 3–6 GB de downloads por motor CUDA ausente, além dos pesos.\nBiblioteca detectada: "+cfg["treino"]+"\nComfyUI: "+cfg["comfy"])
    for k,v in options.items():ttk.Checkbutton(frame,text=k,variable=v,command=refresh).pack(anchor="w")
    ttk.Label(frame,textvariable=info,wraplength=660).pack(anchor="w",pady=8)
    caption=tk.StringVar(value=cfg.get("modelo_caption",""))
    def select_llm():
        model=filedialog.askopenfilename(title="Modelo visual GGUF",filetypes=[("GGUF","*.gguf")])
        if not model:return
        projector=filedialog.askopenfilename(title="Projetor visual correspondente",filetypes=[("GGUF","*.gguf")])
        if not projector:return
        cfg.pop("llm_download",None)
        cfg.update(modelo_caption=model,projetor=projector)
        write_json(CONF,cfg);caption.set(model);options["Caption"].set(True);refresh()
    ttk.Button(frame,text="Selecionar LLM e projetor locais…",command=select_llm).pack(anchor="w")
    def remote(kind):
        try:
            if kind=="Caption":
                urls={}
                for key,title in (("modelo_caption","LLM visual GGUF"),("projetor","Projetor GGUF correspondente")):
                    url=simpledialog.askstring(title,"URL pública do Hugging Face (/resolve/…):",parent=win)
                    if not url:return
                    url=url.strip();custom_asset(url,".gguf");urls[key]=url
                cfg["llm_download"]=urls;caption.set(urls["modelo_caption"]);options["Caption"].set(True)
            else:
                url=simpledialog.askstring("Base de teste","URL pública do arquivo .safetensors (/resolve/…):",parent=win)
                if not url:return
                url=url.strip();custom_asset(url,".safetensors");cfg["teste_download"]=url
                options["Base de teste"].set(True)
            write_json(CONF,cfg);refresh()
        except ValueError as exc:messagebox.showerror("Modelo",str(exc))
    ttk.Button(frame,text="Baixar outro LLM e projetor…",command=lambda:remote("Caption")).pack(anchor="w")
    ttk.Button(frame,text="Baixar base para testar LoRA…",command=lambda:remote("Base de teste")).pack(anchor="w")
    ttk.Label(frame,textvariable=caption,wraplength=640).pack(anchor="w")
    refresh()
    def go():
        choices=[k for k,v in options.items() if v.get()]
        if not choices:return
        if "Base de teste" in choices and not cfg.get("teste_download"):
            remote("Base de teste")
            if not cfg.get("teste_download"):return
        if not messagebox.askyesno("Instalar",info.get()+"\\nIniciar a instalação?"):return
        log=DATA/"logs/instalacao.log";log.parent.mkdir(parents=True,exist_ok=True)
        with log.open("w",encoding="utf-8") as f:
            proc=subprocess.Popen([sys.executable,"-u",__file__,*choices],stdout=f,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        button.configure(state="disabled")
        def poll():
            if proc.poll() is None:win.after(1000,poll);return
            button.configure(state="normal")
            if proc.returncode:messagebox.showerror("Instalação","Veja o registro em "+str(log))
            else:messagebox.showinfo("Concluído","Componentes preparados. Reabra o HydraTrainer.")
        poll()
    button=ttk.Button(frame,text="Instalar seleção",command=go);button.pack(anchor="e")
    win.mainloop()

if __name__=="__main__":
    if sys.argv[1:]:install(sys.argv[1:])
    else:wizard()

