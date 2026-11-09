import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from platform_paths import VENV_PY, WINDOWS

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("HYDRA_DATA_DIR",ROOT/"dados")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
CONF = DATA / "componentes.json"

def write_json(path, value):
    from uuid import uuid4
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def read_json(path, default=None):
    return json.loads(path.read_text("utf-8-sig")) if path.is_file() else default

from functools import lru_cache

@lru_cache(maxsize=1)
def discover():
    saved = read_json(CONF, {})
    roots = [ROOT.parent, Path(ROOT.anchor)] if WINDOWS else []
    roots += [Path(f"{c}:/") for c in "DECFGH" if WINDOWS and Path(f"{c}:/").is_dir()]
    def locate(paths, check, fallback):
        for path in paths:
            if (path / check).is_file():
                return str(path.resolve())
        return str(fallback)
    engine = locate([ROOT/"componentes/treino"]+[r/"LoraTrainer" for r in roots],
                    Path("trainer/venv") / VENV_PY, ROOT/"componentes/treino")
    comfy = locate([ROOT/"componentes/Comfy"]+[r/"Comfy" for r in roots],
                   "ComfyUI/main.py", ROOT/"componentes/Comfy")
    default = {"treino":engine,"comfy":comfy,"modelos":str(Path(engine)/"models"),
               "python_comfy":str(Path(comfy)/"scripts/venv"/VENV_PY)}
    for r in roots:
        folder = r/"LLM"
        if not folder.is_dir():
            continue
        servers = list(folder.glob("*/llama-server.exe"))
        models = list(folder.glob("**/*abliterated*Q6_K.gguf"))
        projs = list(folder.glob("**/*mmproj*Q8_0.gguf"))
        for model in sorted(folder.glob("**/Qwen3.5-9B-*.gguf")):
            prefix=model.name.rsplit("-",1)[0]
            for projector in model.parent.glob("mmproj-"+prefix+"-*.gguf"):
                default.update(modelo_think=str(model),projetor_think=str(projector))
                break
            if "modelo_think" in default:break
        if servers and models and projs:
            default.update(servidor=str(servers[0]), modelo_caption=str(models[0]), projetor=str(projs[0]))
            break
    return {**default, **saved}

def gpu():
    cols = "index,name,uuid,driver_version,memory.total,memory.free"
    cmd = ["nvidia-smi","--query-gpu="+cols,"--format=csv,noheader,nounits"]
    rows = subprocess.check_output(cmd, text=True, timeout=12, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    cards = [s.strip().split(", ") for s in rows.strip().splitlines()]
    idx,name,uuid,driver,total,free = max(cards, key=lambda c:int(c[4]))
    return dict(index=idx, name=name, uuid=uuid, driver=driver, total=int(total), free=int(free))


