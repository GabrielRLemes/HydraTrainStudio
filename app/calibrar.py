import argparse
import os
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
import psutil
from PIL import Image, ImageDraw
from ambiente import PYTHON, ROOT, environment, TRAINER
from configuracao import gpu, read_json, write_json

SIZES = {"Krea2": {"Ideal":[512], "Recomendado":[640,576,512], "Experimental":[768,704,640,576,512]},
         **{p:{"Ideal":[768,640,512], "Recomendado":[896,768,640,512], "Experimental":[1024,896,768,640,512]} for p in ("Anima","Illustrious")}}
MARGIN = {"Ideal":(1000,1700),"Recomendado":(550,950),"Experimental":(128,384)}
FILE = ROOT/"calibracao.json"
def targets(profile,preset,card):
    options=SIZES[profile][preset]
    if card["total"] >= 22000:
        larger={"Krea2":{"Ideal":[768,640],"Recomendado":[896,768],"Experimental":[1024,896]},
                "Anima":{"Ideal":[1024,896],"Recomendado":[1152,1024],"Experimental":[1280,1152]},
                "Illustrious":{"Ideal":[1024,896],"Recomendado":[1152,1024],"Experimental":[1280,1152]}}
        return list(dict.fromkeys(larger[profile][preset]+options))
    if card["total"]<10000 and profile!="Krea2":
        return [s for s in options if s<=768]+[s for s in (640,512) if s not in options]
    return options

def signature(card):
    marker = TRAINER/".git/refs/heads/main"
    engine = marker.read_text().strip() if marker.is_file() else (TRAINER/".hydra-commit").read_text().strip() if (TRAINER/".hydra-commit").is_file() else str(TRAINER)
    from importlib.metadata import version,PackageNotFoundError
    try:
        torch_version=version("torch")
    except PackageNotFoundError:
        dirs=list((TRAINER/"venv/Lib/site-packages").glob("torch-*.dist-info"))
        torch_version=dirs[0].name[6:-10] if dirs else "ausente"
    return "|".join(map(str,(card["uuid"],card["driver"],card["total"],round(psutil.virtual_memory().total/2**30),engine,torch_version)))

def report(profile, preset, card=None):
    card = card or gpu()
    values=read_json(FILE,{}).get(signature(card),{}).get(profile,{})
    vram,ram=MARGIN[preset]
    for res in targets(profile,preset,card):
        v=values.get(str(res),{})
        if v.get("ok") and (profile!="Illustrious" or v.get("motor_rev")==2) and v["livre_gpu_min"]>=vram and v["livre_ram_min"]>=ram:
            return res
    return None

def probe(profile, res, card):
    directory=ROOT/"calibracoes"/f"{profile}-{res}-{uuid4().hex[:8]}"
    dataset=directory/"amostra"
    dataset.mkdir(parents=True)
    for i,color in enumerate(("red","blue")):
        im=Image.new("RGB",(res,res),"white")
        ImageDraw.Draw(im).ellipse((res//4,res//4,3*res//4,3*res//4),fill=color)
        im.save(dataset/f"{i}.png")
        (dataset/f"{i}.txt").write_text(f"A {color} circle on a white square background.",encoding="utf-8")
    cmd=[str(PYTHON),str(Path(__file__).with_name("treinar.py")),profile,str(dataset),"Calibracao","--passos","2","--res",str(res),"--sonda"]
    env=environment()
    env["CUDA_VISIBLE_DEVICES"]=card["index"]
    print(f"Medindo {profile} {res} px · {directory}",flush=True)
    minfree=card["free"]
    start_ram=psutil.virtual_memory().available//2**20
    minram=start_ram
    with (directory/"motor.log").open("w",encoding="utf-8") as log:
        proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            import pynvml as nv
            nv.nvmlInit()
            handle=nv.nvmlDeviceGetHandleByUUID(card["uuid"])
            while proc.poll() is None:
                minfree=min(minfree,nv.nvmlDeviceGetMemoryInfo(handle).free//2**20)
                minram=min(minram,psutil.virtual_memory().available//2**20)
                time.sleep(.35)
        finally:
            if proc.poll() is None:
                if os.name!="nt":
                    import psutil
                    for child in psutil.Process(proc.pid).children(recursive=True):child.kill()
                    proc.kill();proc.wait()
                else:subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],capture_output=True)
    ok=proc.returncode==0
    result={"motor_rev":2,"ok":ok,"livre_gpu_inicio":card["free"],"livre_gpu_min":minfree,"livre_ram_min":minram,"livre_ram_inicio":start_ram,"log":str(directory/"motor.log"),"quando":time.strftime("%Y-%m-%d %H:%M")}
    saved=read_json(FILE,{})
    saved.setdefault(signature(card),{}).setdefault(profile,{})[str(res)]=result
    write_json(FILE,saved)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

def calibrate(profile,preset,refresh=False):
    card=gpu()
    for res in targets(profile,preset,card):
        v=read_json(FILE,{}).get(signature(card),{}).get(profile,{}).get(str(res))
        if refresh or not v or not v.get("ok") or (profile=="Illustrious" and v.get("motor_rev")!=2):
            v=probe(profile,res,card)
            if not v["ok"]:
                log=Path(v["log"]).read_text("utf-8",errors="replace").lower()
                if not any(e in log for e in ("out of memory","not enough memory","paging file","1455","cannot allocate","insuficiente")):
                    raise RuntimeError("Falha do motor. Consulte "+v["log"])
        a,b=MARGIN[preset]
        if v["ok"] and v["livre_gpu_min"]>=a and v["livre_ram_min"]>=b:
            print(f"Validado: {res} px para {profile} / {preset}",flush=True)
            return res
    raise RuntimeError("Nenhum alvo passou com a margem deste preset.")

if __name__=="__main__":
    args=argparse.ArgumentParser()
    args.add_argument("perfil",choices=SIZES)
    args.add_argument("preset",choices=MARGIN)
    args.add_argument("--medir",type=int)
    a=args.parse_args()
    if a.medir:
        if not probe(a.perfil,a.medir,gpu())["ok"]:sys.exit(1)
    else:
        calibrate(a.perfil,a.preset)

