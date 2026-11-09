from pathlib import Path
import os

from configuracao import DATA as ROOT, discover
CFG = discover()
LIB = Path(CFG["treino"])
MODELS = Path(CFG["modelos"])
LORAS = ROOT / "loras"
TRAINER = LIB / "trainer"
from platform_paths import VENV_PY
PYTHON = TRAINER / "venv" / VENV_PY
COMFY = Path(CFG["comfy"])
PROFILES = ("Krea2", "Anima", "Illustrious")
SIZE = {"Krea2": 512, "Anima": 768, "Illustrious": 768}
from configuracao import ROOT as INSTALL
PRIVATE_MODELS=INSTALL/"componentes/pesos"
def model(name):
    path=MODELS/name
    return path if path.is_file() else PRIVATE_MODELS/name
VAE = model("vae/qwen_image_vae.safetensors")
RAW = model("diffusion_models/krea2_raw_int8_convrot.safetensors")
TURBO = model("diffusion_models/krea2_turbo_int8_convrot.safetensors")
ANIMA = model("diffusion_models/anima-base-v1.0.safetensors")
XL = model("checkpoints/Illustrious-XL-v0.1.safetensors")
ENC_K = model("text_encoders/qwen3vl_4b_bf16.safetensors")
ENC_A = model("text_encoders/qwen_3_06b_base.safetensors")


def environment():
    env = {**os.environ, "HF_HOME": str(LIB / "cache/huggingface"),
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "2", "PYTHONNOUSERSITE": "1",
           "TRITON_CACHE_DIR": str(ROOT / "cache/triton")}
    env.pop("PYTHONPATH", None)
    return env
