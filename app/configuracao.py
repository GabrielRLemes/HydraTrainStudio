import json
import os
import subprocess
from pathlib import Path

from platform_paths import VENV_PY

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("HYDRA_DATA_DIR",ROOT/"dados")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
CONF = DATA / "componentes.json"

from engine_lock import managed_path, TRAIN_COMMIT, COMFY_COMMIT

COMPONENTS = ROOT / "componentes"
MANAGED_TRAIN = managed_path(COMPONENTS, "treino", "amenorira/lora-scripts-anima", TRAIN_COMMIT)
MANAGED_COMFY = managed_path(COMPONENTS, "Comfy", "comfyanonymous/ComfyUI", COMFY_COMMIT)
MANAGED_LLAMA = managed_path(COMPONENTS, "llama.cpp", "ggml-org/llama.cpp", "b11900")


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
    # External executables are selected in Settings and persisted in CONF.
    default = {"treino":str(MANAGED_TRAIN), "comfy":str(MANAGED_COMFY), "modelos":str(COMPONENTS/"pesos"),
               "python_comfy":str(MANAGED_COMFY/"scripts/venv"/VENV_PY)}
    for key, parent in (("treino", "treino"), ("comfy", "Comfy"), ("python_comfy", "Comfy"), ("servidor", "llama.cpp")):
        value = Path(saved.get(key) or ".")
        if value.is_relative_to(COMPONENTS/parent) and value != Path(default.get(key, MANAGED_LLAMA/"build/bin/llama-server")):
            saved.pop(key)
    return {**default, **saved}

def gpu():
    cols = "index,name,uuid,driver_version,memory.total,memory.free"
    cmd = ["nvidia-smi","--query-gpu="+cols,"--format=csv,noheader,nounits"]
    rows = subprocess.check_output(cmd, text=True, timeout=12, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    cards = [s.strip().split(", ") for s in rows.strip().splitlines()]
    idx,name,uuid,driver,total,free = max(cards, key=lambda c:int(c[4]))
    return dict(index=idx, name=name, uuid=uuid, driver=driver, total=int(total), free=int(free))


