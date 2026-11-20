"""Apply the Windows setup wizard's selections using the shared component installer."""
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

from componentes import ASSETS, COMP, custom_asset, fetch, install
from configuracao import DATA, discover, read_json, write_json

FAMILIES = {
    "Krea 2 Raw": ("Krea2", "diffusion_models/krea2_raw_int8_convrot.safetensors"),
    "Anima Base": ("Anima", "diffusion_models/anima-base-v1.0.safetensors"),
    "Illustrious XL v0.1": ("Illustrious", "checkpoints/Illustrious-XL-v0.1.safetensors"),
}
TURBO = "diffusion_models/krea2_turbo_int8_convrot.safetensors"
DOWNLOAD = "Download the suggested model"
LOCAL = "Use a model on this PC"
URL = "Use a Hugging Face file link"
LATER = "Set up later"


def materialize(plan, key, suffix, *, projector=False, official=None, library=None):
    mode = plan[key]
    value = plan[key + mode + (" projector" if projector else "")]
    if mode == URL:
        cached = custom_asset(value, suffix)
        if official:
            return fetch(value, library / official["name"], official["sha"])
        return fetch(value, cached)
    if mode != LOCAL:
        raise ValueError("Unknown model source")
    src = Path(value).resolve(strict=True)
    if not src.is_file() or src.suffix.lower() != suffix:
        raise ValueError(f"Invalid model file: {src}")
    if official:
        dest = library / official["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src == dest.resolve():
            with src.open("rb") as stream:
                if hashlib.file_digest(stream,"sha256").hexdigest() != official["sha"]:
                    raise ValueError(f"Incorrect official weights: {src}")
        else:
            with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
                staged = Path(tmp) / "weight"
                shutil.copyfile(src, staged)
                with staged.open("rb") as stream:
                    if hashlib.file_digest(stream,"sha256").hexdigest() != official["sha"]:
                        raise ValueError(f"Incorrect official weights: {src}")
                staged.replace(dest)
        return dest
    return src


def apply(plan):
    cfg = dict(discover())
    assets = {item["name"]: item for item in ASSETS}
    choices = set()
    skipped = set()
    tests = dict(cfg.get("test_models", {}))
    need_comfy = False
    for label, (family, name) in FAMILIES.items():
        if plan.get("select:"+label) != "True":
            continue
        choices.add(family)
        if plan[label] != DOWNLOAD:
            materialize(plan,label,".safetensors",official=assets[name],library=Path(cfg["modelos"]))
        key = "test:"+label
        tests.pop(family,None)
        if family == "Krea2" and plan[key] != DOWNLOAD:
            skipped.add(TURBO)
        if plan[key] == LATER:
            continue
        need_comfy = True
        if plan[key] != DOWNLOAD:
            from comparar import remember_model
            tests[family] = remember_model(materialize(plan,key,".safetensors"))
    cfg["test_models"] = tests
    for label, component, keys in (
        ("Qwen3-VL","Caption",("modelo_caption","projetor")),
        ("JoyCaption Beta One","JoyCaption",("joy_model","joy_projector")),
    ):
        if plan.get("select:"+label) != "True":
            continue
        choices.add(component)
        if component == "Caption":
            cfg.pop("llm_download",None)
        if plan[label] == DOWNLOAD:
            for key in keys:
                cfg.pop(key,None)
        else:
            for i,key in enumerate(keys):
                cfg[key] = str(materialize(plan,label,".gguf",projector=bool(i)))
            if component == "JoyCaption":
                skipped.update(n for n in assets if n.startswith("joycaption/"))
    if need_comfy:
        if plan["comfy"].startswith("Use"):
            src = Path(plan["comfyFolder"])
            py = Path(plan["comfyPython"])
            if src.name.lower()!="comfyui" or not (src/"main.py").is_file() or not py.is_file() or py.name.lower()!="python.exe":
                raise ValueError("Select a valid ComfyUI installation and its Python interpreter.")
            cfg.update(comfy=str(src.parent),python_comfy=str(py))
        else:
            choices.add("ComfyUI")
    print("Preparing components:", ", ".join(sorted(choices)) or "Studio only", flush=True)
    install(choices,cfg=cfg,skip_assets=skipped)
    if not (DATA/"idioma.json").exists():
        write_json(DATA/"idioma.json",{"idioma":"English"})
    (DATA/"componentes-apresentados").touch()


if __name__=="__main__":
    apply(read_json(Path(sys.argv[1])))
