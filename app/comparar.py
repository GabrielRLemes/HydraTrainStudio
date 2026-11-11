import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from uuid import uuid4
from ambiente import LORAS, ROOT, SIZE
from configuracao import read_json,write_json
from testar import graph,generate,server

def inspect_weight(path):
    with path.open("rb") as f:
        size=struct.unpack("<Q", f.read(8))[0]
        if size>100_000_000:raise ValueError(f"Cabeçalho inválido: {path}")
        header=json.loads(f.read(size))
        offset=f.tell()
        digest=hashlib.sha256()
        for name in sorted(k for k in header if k!="__metadata__"):
            info=header[name]
            lo,hi=info["data_offsets"]
            digest.update(json.dumps([name,info["dtype"],info["shape"]]).encode())
            f.seek(offset+lo)
            left=hi-lo
            while left>0:
                data=f.read(min(left,2**20))
                if not data:raise ValueError(f"Checkpoint incompleto: {path}")
                digest.update(data)
                left-=len(data)
    return header.get("__metadata__",{}),digest.hexdigest()

def versions(run):
    spec=read_json(run/"treino.json",{})
    found={}
    for path in sorted(run.glob("*.safetensors")):
        md,sha=inspect_weight(path)
        step=md.get("ss_steps")
        match=re.search(r"(?:step|steps)[-_]?(\d+)",path.stem,re.I)
        final=path.stem==spec.get("nome")
        step=int(step) if step else int(match[1]) if match else int(spec.get("passos",0)) if final else None
        row={"arquivo":str(path.relative_to(LORAS)), "passo":step,"final":final,"sha":sha}
        if sha not in found or final:found[sha]=row
    return sorted(found.values(),key=lambda r:(r["passo"] is None,r["passo"] or 0,r["final"],r["arquivo"]))

def plan(run,prompts,seeds,strength=.85,subset=None,test_model=None,ranking=False):
    run=run.resolve()
    profile=run.relative_to(LORAS.resolve()).parts[0]
    rows=versions(run)
    if subset is not None:rows=[r for r in rows if r["sha"] in subset]
    if not rows:raise ValueError("Nenhum checkpoint selecionado.")
    prompts=[p.strip() for p in prompts]
    if not prompts or not all(prompts) or len(prompts)!=len(seeds):raise ValueError("Preencha os prompts de teste.")
    rows.insert(0,{"arquivo":"","sha":"base","passo":0,"final":False})
    dest=ROOT/"comparacoes"/(profile+"-"+uuid4().hex[:10])
    spec=read_json(run/"treino.json",{})
    manifest={"perfil":profile,"treino":str(run.relative_to(LORAS)), "res":spec.get("resolucao",SIZE[profile]),
              "prompts":prompts,"sementes":seeds,"forca":strength,"versoes":rows,"imagens":{},"favoritos":[]}
    if test_model:
        path=Path(test_model).resolve(strict=True)
        if path.suffix.lower()!=".safetensors":raise ValueError("Selecione uma base .safetensors da mesma família.")
        manifest.update(modelo_teste=str(path),modelo_bytes=path.stat().st_size,modelo_mtime=path.stat().st_mtime_ns)
    manifest["ranking"]=ranking
    if ranking:
        from random import SystemRandom
        rng=SystemRandom()
        candidates=list(range(1,len(rows)))
        manifest["podium_order"]=[rng.sample(candidates,len(candidates)) for _ in prompts]
    write_json(dest/"grade.json",manifest)

    return dest

def compare(dest):
    file=dest/"grade.json"
    m=read_json(file)
    total=len(m["prompts"])*(len(m["versoes"])-int(m.get("ranking",False)))
    SIZE[m["perfil"]]=m["res"]
    model=m.get("modelo_teste",m.get("test_model"))
    if model and "modelo_bytes" in m:
        stat=Path(model).stat()
        if (stat.st_size,stat.st_mtime_ns)!=(m["modelo_bytes"],m["modelo_mtime"]):raise ValueError("A base de teste mudou. Crie uma nova comparação.")
    with server(dest,model,m["perfil"]) as engine:
        for j,p in enumerate(m["prompts"]):
            for i,r in enumerate(m["versoes"]):
                if i==0 and m.get("ranking"):continue
                key=f"{i}-{j}"
                if key in m["imagens"] and (dest/m["imagens"][key]).is_file():continue
                workflow=graph(m["perfil"],r["arquivo"],p,m["forca"] if i else 0,m["sementes"][j],base=Path(model).name if model else None)
                workflow["10"]["inputs"]["filename_prefix"]=f"linha-{i:02}-prompt-{j+1}"
                write_json(dest/(key+".json"),workflow)
                if m.get("podium_order"):
                    print(f"Ranking {j+1}/{len(m['prompts'])} · {len(m['imagens'])+1}/{total}",flush=True)
                else:print(f"Gerando {len(m['imagens'])+1}/{total} · passo {r['passo']} · prompt {j+1}",flush=True)
                path=generate(engine,dest,workflow)
                m=read_json(file)
                m["imagens"][key]=path.name
                write_json(file,m)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("pasta",type=Path)
    compare(p.parse_args().pasta)

