"""Soma ponderada de adaptadores LoRA clássicos, concatenando os fatores."""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
import tempfile
from uuid import uuid4
from ambiente import LORAS,PROFILES,SIZE
from configuracao import write_json

def merge(family,paths,weights,name,runid=None):
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file
    files=[Path(p).resolve(strict=True) for p in paths]
    if len(files)<2 or len(weights)!=len(files) or len(set(files))!=len(files):raise ValueError("Escolha pelo menos dois arquivos distintos, cada um com seu peso.")
    if not all(math.isfinite(v) for v in weights) or not any(weights):raise ValueError("Use pesos finitos; pelo menos um deve ser diferente de zero.")
    expected={"Krea2":("krea2","networks.lora_krea2"),"Anima":("anima","networks.lora_anima"),"Illustrious":("sdxl_base_v1-0","networks.lora")}[family]
    suffixes=(".lora_down.weight",".lora_up.weight",".alpha")
    output={};layers=set();metadata=[]
    with ExitStack() as stack:
        readers=[stack.enter_context(safe_open(str(p),framework="pt",device="cpu")) for p in files]
        for reader,path in zip(readers,files):
            meta=reader.metadata() or {};metadata.append(meta)
            if (meta.get("ss_base_model_version"),meta.get("ss_network_module"))!=expected:
                raise ValueError(f"Família ou formato incompatível em {path.name}. Escolha LoRAs clássicos do perfil {family}.")
            keys=set(reader.keys()); current=set()
            for k in keys:
                suffix=next((s for s in suffixes if k.endswith(s)),None)
                if not suffix:raise ValueError(f"Tipo de peso não suportado: {k}")
                current.add(k[:-len(suffix)])
            if not current:raise ValueError(f"LoRA vazio: {path}")
            if any(layer+s not in keys for layer in current for s in suffixes[:2]):raise ValueError(f"Fatores incompletos: {path.name}")
            layers.update(current)
        base_names={m["ss_sd_model_name"] for m in metadata if m.get("ss_sd_model_name")}
        if len(base_names)>1:raise ValueError("Os metadados indicam modelos base diferentes.")
        keysets=[set(r.keys()) for r in readers]
        for layer in sorted(layers):
            downs=[];ups=[]; shape=None
            for reader,keys,mult in zip(readers,keysets,weights):
                if not mult or layer+suffixes[0] not in keys:continue
                down=reader.get_tensor(layer+suffixes[0]).float()
                up=reader.get_tensor(layer+suffixes[1]).float()
                rank=down.shape[0]
                if down.ndim not in (2,4) or up.ndim!=down.ndim or not rank or up.shape[1]!=rank:
                    raise ValueError(f"Formato de fatores inválido em {layer}.")
                layout=(tuple(down.shape[1:]),up.shape[0],tuple(up.shape[2:]))
                if shape is not None and shape!=layout:raise ValueError(f"Dimensões incompatíveis em {layer}.")
                shape=layout
                alpha=reader.get_tensor(layer+".alpha").item() if layer+".alpha" in keys else rank
                downs.append(down);ups.append(up*(mult*alpha/rank))
            if not downs:continue
            a=torch.cat(downs,dim=0); b=torch.cat(ups,dim=1)
            if not torch.isfinite(a).all() or not torch.isfinite(b).all():raise ValueError(f"Valores inválidos em {layer}.")
            output[layer+suffixes[0]]=a;output[layer+suffixes[1]]=b;output[layer+".alpha"]=torch.tensor(float(a.shape[0]))
    if not output:raise ValueError("Nenhuma camada resultante.")
    label=re.sub(r"[^a-zA-Z0-9_-]+","-",name).strip("-")[:64] or "Mescla"
    parent=LORAS/family;parent.mkdir(parents=True,exist_ok=True)
    runid=runid or uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}",runid):raise ValueError("ID de saída inválido.")
    dest=parent/f"{label}-{runid}"
    meta={"ss_base_model_version":expected[0],"ss_network_module":expected[1],"ss_output_name":label}
    if base_names:meta["ss_sd_model_name"]=base_names.pop()
    with tempfile.TemporaryDirectory(dir=parent,prefix=".mesclando-") as tmp:
        stage=Path(tmp)/"saida";stage.mkdir()
        save_file(output,str(stage/(label+".safetensors")),metadata=meta)
        write_json(stage/"treino.json",{"nome":label,"perfil":family,"resolucao":SIZE[family],"tipo":"mescla",
            "fontes":[{"arquivo":str(p),"peso":v} for p,v in zip(files,weights)]})
        stage.rename(dest)
    print("LoRA mesclado:",dest/(label+".safetensors"),flush=True)
    return dest

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("perfil",choices=PROFILES);cli.add_argument("nome");cli.add_argument("--entrada",action="append",nargs=2,required=True)
    cli.add_argument("--id");args=cli.parse_args()
    merge(args.perfil,[v[0] for v in args.entrada],[float(v[1]) for v in args.entrada],args.nome,args.id)

