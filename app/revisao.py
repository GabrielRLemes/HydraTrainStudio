import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from PIL import Image
from configuracao import DATA, write_json
from core import render_dataset_image
from dataset import Dataset

FIT="Recortar 1:1"
def field(profile):
    return "krea" if profile=="Krea2" else "sdxl"
def selected(it):
    return not it.get("removed") and it.get("status") not in ("rejeitado","duplicado")

def state(it,profile,res):
    return {"perfil":profile,"res":res,"crop":dict(it.get("crop") or {}),"legenda":(it.get(field(profile)) or "").strip(),
            "fonte":it.get("sha256","")}

def ready(it,profile,res):
    a=it.get("hydra_aprovacao") or {}
    return bool(it.get("status")=="aprovado" and a.get("estado")==state(it,profile,res) and a.get("png") and a.get("sha256"))

def preview(project,key,res):
    return render_dataset_image(project.path_for(project.items[key]),res,project.items[key].get("crop") or {},FIT)

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def approve(project,key,profile,res,image):
    it=project.items[key]
    stamp=state(it,profile,res)
    if not stamp["legenda"]:
        raise ValueError("Revise a legenda do perfil antes de aprovar.")
    if image.size!=(res,res):
        raise ValueError("A prévia não corresponde ao preset.")
    folder=project.root/"revisados"; folder.mkdir(exist_ok=True)
    temp=folder/(uuid4().hex+".png")
    image.save(temp)
    sha=digest(temp); final=folder/(sha+".png")
    temp.replace(final)
    it.update(status="aprovado", hydra_aprovacao={"estado":stamp,"png":final.name,"sha256":sha})
    project.save_one(key)

def materialize(project,profile,res):
    items=[(k,v) for k,v in project.items.items() if selected(v)]
    if not items or any(not ready(it,profile,res) for _,it in items):
        raise ValueError("Há itens pendentes ou a seleção está vazia.")
    dest=DATA/"datasets"/uuid4().hex
    dest.mkdir(parents=True)
    rows=[]
    for i,(key,it) in enumerate(items):
        approval=it["hydra_aprovacao"]
        png=project.root/"revisados"/(approval["sha256"]+".png")
        if digest(png)!=approval["sha256"]:
            raise ValueError("Prévia alterada. Revise novamente "+it["filename"])
        out=dest/f"{i:07}.png"
        shutil.copyfile(png,out)
        out.with_suffix(".txt").write_text(approval["estado"]["legenda"],"utf-8")
        rows.append({"arquivo":out.name,"sha256":approval["sha256"],"frame":key,"origem":it.get("origins",[]),
                     "pts_ms":it.get("pts_ms"),"crop":approval["estado"]["crop"]})
    write_json(dest/"manifesto.json",{"perfil":profile,"res":res,"projeto":project.root.name,"imagens":rows})
    return dest

def _load_source(source,profile,dest):
    source=source.resolve(strict=True)
    if source.is_dir():
        source=next((source/n for n in ("catalogo.sqlite","projeto.json","dataset_manifest.json") if (source/n).is_file()),source)

    if source.suffix.lower() in (".sqlite",".sqlite3",".db") or source.name=="projeto.json":
        base=source.parent
        bank=source if source.suffix!=".json" else base/"catalogo.sqlite"
        if bank.is_file():
            with closing(sqlite3.connect(bank.as_uri()+"?mode=ro",uri=True)) as conn, closing(sqlite3.connect(dest/"catalogo.sqlite")) as copy:
                conn.execute("SELECT id,payload FROM frames LIMIT 1")
                conn.backup(copy)
        else:
            shutil.copyfile(source,dest/"projeto.json")
        for name in ("originais","frames"):
            if (base/name).is_dir():
                shutil.copytree(base/name,dest/name)
        project=Dataset(dest)
    else:
        base=source.parent if source.name=="dataset_manifest.json" else source
        if not base.is_dir():
            raise ValueError("Selecione o manifesto, o banco ou a pasta com imagens.")
        family="Krea2" if profile=="Krea2" else "SDXL"
        folder=base/family if (base/family).is_dir() else base
        manifest=base/"dataset_manifest.json"
        if manifest.is_file() and folder==base:
            alternatives=[base/n for n in ("Krea2","SDXL") if (base/n).is_dir()]
            if not alternatives: raise ValueError("As imagens do manifesto não foram encontradas.")
            folder=alternatives[0]
        project=Dataset(dest)
        rows={}
        if manifest.is_file():
            rows={r["filename"]:r for r in json.loads(manifest.read_text("utf-8-sig"))["images"]}
        for img in sorted(folder.iterdir()):
            if img.suffix.lower() not in (".png",".jpg",".jpeg",".webp",".bmp"):continue
            key,_=project.import_file(img)
            it=project.items[key]
            row=rows.get(img.name,{})
            for name in ("sdxl","krea","origins","pts_ms","frame_uid","media_uid"):
                if name in row:
                    if name in ("media_uid","frame_uid"):it["origem_"+name]=row[name]
                    else:it[name]=row[name]
            side=img.with_suffix(".txt")
            if side.is_file():
                target="krea" if folder.name=="Krea2" else "sdxl" if folder.name=="SDXL" else field(profile)
                it[target]=side.read_text("utf-8-sig").strip()
            it["tags"]=[v.strip() for v in (it.get("sdxl") or "").split(",") if v.strip()]
            it["sdxl_edited"]=bool(it.get("sdxl"))
            it["caption_edited"]=bool(it.get("krea"))
    if not project.items:
        project.close()
        raise ValueError("A fonte não contém imagens ou frames.")
    for it in project.items.values():
        it.pop("hydra_aprovacao",None)
        if selected(it):it["status"]="pendente"
    project.save()
    return project


def import_project(source,profile):
    import tempfile
    parent=DATA/"projetos"
    parent.mkdir(parents=True,exist_ok=True)
    dest=parent/("Importado-"+uuid4().hex[:10])
    with tempfile.TemporaryDirectory(dir=parent,prefix=".importacao-") as tmp:
        stage=Path(tmp)/"projeto"
        stage.mkdir()
        project=_load_source(source,profile,stage)
        project.close()
        stage.rename(dest)
    return Dataset(dest)
