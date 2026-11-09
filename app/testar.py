from contextlib import contextmanager
from ambiente import LORAS, CFG, PRIVATE_MODELS
import yaml
import argparse
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from ambiente import ANIMA, COMFY, ENC_A, ENC_K, MODELS, PROFILES, ROOT, SIZE, TURBO, VAE, XL, environment


def graph(profile, lora, prompt, strength, seed, steps=None, base=None):
    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    sdxl = profile == "Illustrious"
    krea = profile == "Krea2"
    nodes = {}
    if sdxl:
        nodes["1"] = node("CheckpointLoaderSimple", ckpt_name=base or XL.name)
        clip, vae = ["1", 1], ["1", 2]
    else:
        nodes["1"] = node("UNETLoader", unet_name=base or (TURBO if krea else ANIMA).name, weight_dtype="default")
        nodes["2"] = node("CLIPLoader", clip_name=(ENC_K if krea else ENC_A).name,
                          type="krea2" if krea else "stable_diffusion", device="default")
        nodes["3"] = node("VAELoader", vae_name=VAE.name)
        clip, vae = ["2", 0], ["3", 0]
    model = ["1", 0]
    if strength:
        nodes["4"] = node("LoraLoaderModelOnly", model=model, lora_name=lora, strength_model=strength)
        model = ["4", 0]
    nodes["5"] = node("CLIPTextEncode", clip=clip, text=prompt)
    nodes["6"] = node("CLIPTextEncode", clip=clip, text="" if krea else "worst quality, blurry")
    nodes["7"] = node("EmptyLatentImage",
                      width=SIZE[profile], height=SIZE[profile], batch_size=1)
    nodes["8"] = node("KSampler", model=model, positive=["5", 0], negative=["6", 0], latent_image=["7", 0],
                      seed=seed, steps=steps or {"Krea2": 8, "Anima": 30, "Illustrious": 24}[profile],
                      cfg={"Krea2": 1, "Anima": 4, "Illustrious": 5}[profile],
                      sampler_name="er_sde" if profile == "Anima" else "euler",
                      scheduler="normal" if sdxl else "simple", denoise=1)
    nodes["9"] = node("VAEDecode", samples=["8", 0], vae=vae)
    nodes["10"] = node("SaveImage", images=["9", 0], filename_prefix=profile + ("_LoRA" if strength else "_Base"))
    return nodes


@contextmanager
def server(dest,test_model=None,profile=None):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    def api(path, data=None):
        req = urllib.request.Request(address + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as reply:
                return json.load(reply)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode()) from exc

    dest.mkdir(parents=True, exist_ok=True)
    LORAS.mkdir(parents=True, exist_ok=True)
    extra = dest / "biblioteca.yaml"
    paths={"hydratrainer":{"base_path":str(ROOT),"loras":"loras"}}
    if PRIVATE_MODELS.is_dir():
        paths["pesos_locais"]={"base_path":str(PRIVATE_MODELS), **{k:k for k in ("vae","diffusion_models","text_encoders","checkpoints")}}
    if test_model:
        selected=Path(test_model)
        if not selected.is_file():raise FileNotFoundError(selected)
        kind="checkpoints" if profile=="Illustrious" else "diffusion_models"
        paths["modelo_teste"]={"base_path":str(selected.parent),kind:".","is_default":True}
    extra.write_text(yaml.safe_dump(paths),encoding="utf-8")
    base = ROOT / "cache/comfy"
    base.mkdir(parents=True, exist_ok=True)
    cmd = [Path(CFG["python_comfy"]), "-s", COMFY / "ComfyUI/main.py",
           "--base-directory", base, "--models-directory", MODELS, "--output-directory", dest,
           "--port", str(port), "--listen", "127.0.0.1", "--extra-model-paths-config", extra, "--offline", "--disable-all-custom-nodes",
           "--lowvram", "--preview-method", "none"]
    print("Iniciando ComfyUI para o teste. Log:", dest / "comfy.log", flush=True)
    with (dest / "comfy.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(list(map(str, cmd)), cwd=COMFY / "ComfyUI", env=environment(),
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(180):
                if proc.poll() is not None:
                    raise RuntimeError("ComfyUI encerrou. Consulte " + str(dest / "comfy.log"))
                try:
                    api("/system_stats")
                    break
                except (OSError, TimeoutError):
                    time.sleep(1)
            else:
                raise TimeoutError("ComfyUI não iniciou em três minutos.")
            yield api, proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()

def generate(session, dest, workflow):
    api, proc = session
    key = api("/prompt", {"prompt":workflow})["prompt_id"]
    while proc.poll() is None:
        entry = api("/history/"+key).get(key)
        if entry:
            if entry["status"]["status_str"] != "success":
                raise RuntimeError(str(entry["status"]["messages"])[-3500:])
            image = entry["outputs"]["10"]["images"][0]
            path = dest / image.get("subfolder","") / image["filename"]
            if not path.is_file():
                raise RuntimeError(f"Resultado ausente: {path}")
            return path
        time.sleep(0.5)
    raise RuntimeError(f"ComfyUI encerrou; consulte {dest / 'comfy.log'}")
