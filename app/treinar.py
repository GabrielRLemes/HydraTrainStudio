import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import toml

from ambiente import ANIMA, ENC_A, ENC_K, MODELS, PROFILES, PYTHON, RAW, ROOT, SIZE, TRAINER, VAE, XL, environment
from ambiente import LORAS
from configuracao import write_json, gpu
from PIL import Image
import shutil


def train(profile, source, name, steps, res, interval=0, probe=False, lr=.0001, advanced=None):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:5]
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:55] or "LoRA"
    job = ROOT / "treinos" / f"{profile}-{label}-{stamp}"
    output = (ROOT / "sondas" if probe else LORAS) / profile / f"{label}-{stamp}"
    deps = {"Krea2": [RAW, VAE, ENC_K], "Anima": [ANIMA, VAE, ENC_A], "Illustrious": [XL]}
    for file in deps[profile]:
        if not file.is_file():
            raise FileNotFoundError(f"Peso ausente: {file}")
    image_dir = job / "imagens"
    image_dir.mkdir(parents=True)
    count = 0
    for img in sorted(source.glob("*.png")):
        cap = img.with_suffix(".txt")
        with Image.open(img) as view:
            if view.size != (res, res):
                raise ValueError(f"Dimensões diferentes das aprovadas: {img} ({view.size})")
        if not cap.is_file() or not cap.read_text("utf-8-sig").strip():
            raise ValueError(f"Legenda pendente: {img}")
        shutil.copyfile(img, image_dir/img.name)
        shutil.copyfile(cap, image_dir/cap.name)
        count += 1
    if not count:
        raise ValueError("Nenhuma imagem aprovada.")
    steps = steps or max(300, min(2000, count * 35))
    if steps < 1:
        raise ValueError("Número de passos inválido.")
    from avancado import options,target_steps
    opt=options(advanced or {},steps,count)
    steps=target_steps(opt,steps,count)
    print(f"{count} imagens · {steps} passos · {output}", flush=True)
    cfg = job / "dataset.toml"
    if not 0 < lr <= .01:
        raise ValueError("Taxa de aprendizado inválida.")
    interval = interval or max(100, steps // 4)
    output.mkdir(parents=True)
    write_json(output / "treino.json", {"perfil":profile, "nome":label, "passos":steps,
               "intervalo":interval, "taxa":lr, "resolucao":res, "imagens":count, "origem":str(source), "modo":"avancado" if advanced is not None else "automatico","parametros":opt})
    env = environment()
    sd = TRAINER / "vendor/sd-scripts"
    mus = TRAINER / "vendor/musubi-tuner/src"
    env["PYTHONPATH"] = str(mus if profile == "Krea2" else sd)
    general = {"caption_extension": ".txt", "enable_bucket": False}
    args = ["--dataset_config", cfg, "--output_dir", output, "--output_name", label,
            "--network_dim", opt["rank"], "--network_alpha", opt["alpha"], "--optimizer_type", opt["optimizer"],
            "--learning_rate", str(lr), "--mixed_precision", "bf16", "--save_precision", opt["save"],
            "--max_train_steps", steps, "--save_every_n_steps", interval,
            "--max_data_loader_n_workers", opt["workers"], *(["--gradient_checkpointing"] if opt["checkpoint"] else []), "--seed", opt["seed"], "--sdpa"]
    if advanced is not None:
        args.extend(["--gradient_accumulation_steps",opt["accum"],"--lr_scheduler",opt["scheduler"],
                     "--lr_warmup_steps",opt["warmup"],"--max_grad_norm",opt["clip"]])
    card=gpu()
    env["CUDA_VISIBLE_DEVICES"]=card["index"]
    swap = 23 if card["total"] < 10000 else 19 if card["total"] < 15000 else 13 if card["total"] < 22000 else 6 if card["total"] < 32000 else 0
    if profile == "Krea2":
        general.update(resolution=[res, res], batch_size=opt["batch"])
        data = {"image_directory": str(job / "imagens"), "cache_directory": str(job / "cache")}
        entry = mus / "musubi_tuner"
        cmds = [
            [entry / "krea2_cache_latents.py", "--dataset_config", cfg, "--vae", VAE, "--num_workers", "1"],
            [entry / "krea2_cache_text_encoder_outputs.py", "--dataset_config", cfg, "--text_encoder", ENC_K,
             "--batch_size", "1", "--num_workers", "1", *(["--device","cpu"] if card["total"]<10000 else [])],
            [entry / "krea2_train_network.py", *args, "--network_module", "networks.lora_krea2", "--dit", RAW,
             "--vae", VAE, "--convrot_int8", "--blocks_to_swap", str(swap), "--timestep_sampling", "krea2_shift",
             "--weighting_scheme", "none"],
        ]
    else:
        data = {"resolution": [res, res], "batch_size": opt["batch"], "min_bucket_reso": 256, "max_bucket_reso": 1280,
                "bucket_reso_steps": 64, "subsets": [{"image_dir": str(job / "imagens"), "num_repeats": 1}]}
        args += ["--network_train_unet_only", "--cache_latents", "--cache_latents_to_disk",
                 "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk",
                 "--save_model_as", "safetensors", *(["--lr_scheduler","constant"] if advanced is None else [])]
        if profile == "Anima":
            cmds = [[sd / "anima_train_network.py", *args, "--network_module", "networks.lora_anima",
                     "--pretrained_model_name_or_path", ANIMA, "--qwen3", ENC_A, "--vae", VAE,
                     "--qwen_image_vae_2d", "--timestep_sampling", "sigmoid", "--discrete_flow_shift", "1"]]
        else:
            cmds = [[Path(__file__).with_name("illustrious.py"), *args, "--network_module", "networks.lora",
                     "--pretrained_model_name_or_path", XL, "--no_half_vae"]]
    cfg.write_text(toml.dumps({"general": general, "datasets": [data]}), encoding="utf-8")
    for cmd in cmds:
        full = list(map(str, [PYTHON, *cmd]))
        print(subprocess.list2cmdline(full), flush=True)
        subprocess.run(full, cwd=mus.parent if profile == "Krea2" else sd, env=env, check=True)
    final = output / (label + ".safetensors")
    if not final.is_file():
        raise RuntimeError("O treinador terminou sem produzir o LoRA esperado.")
    print("LoRA salvo:", final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("perfil", choices=PROFILES)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("nome")
    parser.add_argument("--passos", type=int, default=0)
    parser.add_argument("--res", type=int, required=True)
    parser.add_argument("--intervalo", type=int, default=0)
    parser.add_argument("--sonda", action="store_true")
    parser.add_argument("--taxa",type=float,default=.0001)
    import json
    parser.add_argument("--avancado",type=json.loads)
    options = parser.parse_args()
    train(options.perfil, options.dataset, options.nome, options.passos, options.res, options.intervalo, options.sonda, options.taxa, options.avancado)
