import hashlib
import re
import json
import shutil
import sqlite3
from contextlib import closing, ExitStack
from pathlib import Path
from uuid import uuid4
from PIL import Image
from configuracao import DATA, write_json
from core import render_dataset_image
from dataset import Dataset
from regioes import confirmed_notes, read_regions, unpack_mask
from local_files import plain_path, project_path
from media import inspect, Settings

FIT="Recortar 1:1"
def field(profile):
    return "krea" if profile=="Krea2" else "sdxl"
def selected(it):
    return not it.get("removed") and it.get("status") not in ("rejeitado","duplicado")

def state(it,profile,res):
    text=(it.get(field(profile)) or "").strip()
    # Keep the editable draft separate so unchecking a region removes its supplement.
    if text:
        for note in confirmed_notes(it):
            phrase=re.escape(note.rstrip(".!?") or note)
            if re.search(r"(?<!\w)"+phrase+r"(?!\w)",text,re.IGNORECASE):continue
            if profile=="Krea2":
                text+=(" " if text.endswith((".","!","?")) else ". ")+note
            else:text+=", "+note
    return {"perfil":profile,"res":res,"crop":dict(it.get("crop") or {}),"legenda":text,
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
        if not re.fullmatch(r"[0-9a-f]{64}", approval["sha256"]):
            raise ValueError("Hash da revisão inválido.")
        png = project_path(project.root, "revisados/"+approval["sha256"]+".png", nested=True)
        if digest(png)!=approval["sha256"]:
            raise ValueError("Prévia alterada. Revise novamente "+it["filename"])
        out=dest/f"{i:07}.png"
        shutil.copyfile(png,out)
        out.with_suffix(".txt").write_text(approval["estado"]["legenda"],"utf-8")
        rows.append({"arquivo":out.name,"sha256":approval["sha256"],"frame":key,"origem":it.get("origins",[]),
                     "pts_ms":it.get("pts_ms"),"crop":approval["estado"]["crop"]})
    write_json(dest/"manifesto.json",{"perfil":profile,"res":res,"projeto":project.root.name,"imagens":rows})
    return dest

def copy_catalog(bank, dest):
    # Never install schema, triggers or views from a supplied database.
    empty = Dataset(dest)
    empty.close()
    files = {"originais": {}, "frames": {}}
    with closing(sqlite3.connect(bank.as_uri()+"?mode=ro", uri=True)) as source, closing(sqlite3.connect(dest/"catalogo.sqlite")) as target:
        source.execute("PRAGMA trusted_schema=OFF")
        source.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16 * 1024**2)
        source.execute("BEGIN")
        types = {row[1]:row[2] for row in source.execute("PRAGMA main.table_list")}
        if any(types.get(name) != "table" for name in ("media", "frames")):
            raise ValueError("Catálogo de mídia inválido.")
        for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if table not in types:
                continue
            if types[table] != "table":
                raise ValueError("Tipo de tabela inválido no catálogo.")
            columns = [r[1] for r in target.execute(f"PRAGMA table_info({table})")]
            names = ",".join(columns)
            marks = ",".join("?" for _ in columns)
            rows = source.execute(f"SELECT {names} FROM {table}")
            target.executemany(f"INSERT INTO {table} ({names}) VALUES ({marks})", rows)
        for name, sha, kind in target.execute("SELECT filename,sha,kind FROM media"):
            files["originais"][name] = (sha, kind, False)
        for (payload,) in target.execute("SELECT payload FROM frames"):
            item = json.loads(payload)
            for region in read_regions(item):
                unpack_mask(region["mask"])
            folder = "originais" if item.get("frame_index") is None else "frames"
            files[folder][item["filename"]] = (item.get("sha256"), "image", selected(item))
        target.commit()
    return files


def _load_source(source,profile,dest,resources):
    source=plain_path(source).resolve(strict=True)
    if source.is_dir():
        source=next((source/n for n in ("catalogo.sqlite","projeto.json","dataset_manifest.json") if project_path(source,n).is_file()),source)

    if source.suffix.lower() in (".sqlite",".sqlite3",".db") or source.name=="projeto.json":
        base=source.parent
        bank=source if source.suffix!=".json" else base/"catalogo.sqlite"
        if plain_path(bank).is_file():
            files = copy_catalog(bank, dest)
        else:
            if source.stat().st_size > 128 * 1024**2:
                raise ValueError("Projeto JSON acima de 128 MiB.")
            raw = json.loads(source.read_text("utf-8-sig"))
            files = {"originais": {it["filename"]:(None,"image",True) for it in raw.get("items", {}).values()}}
            shutil.copyfile(source,dest/"projeto.json")
        for folder, names in files.items():
            target = dest / folder
            target.mkdir(exist_ok=True)
            origin = project_path(base,folder)
            settings = Settings()
            for name, (sha, kind, required) in names.items():
                path = project_path(origin,name)
                if not path.is_file() and not required:
                    continue
                if not path.is_file() or path.stat().st_size > settings.max_mb * 1024**2:
                    raise ValueError(f"Mídia ausente ou acima do limite: {name}")
                local = project_path(target,name)
                shutil.copyfile(path,local)
                actual, _, _ = inspect(local,settings)
                if actual != kind or (sha is not None and digest(local) != sha):
                    raise ValueError(f"Mídia diferente do catálogo: {name}")
        project=resources.enter_context(closing(Dataset(dest)))
    else:
        base=source.parent if source.name=="dataset_manifest.json" else source
        if not base.is_dir():
            raise ValueError("Selecione o manifesto, o banco ou a pasta com imagens.")
        family="Krea2" if profile=="Krea2" else "SDXL"
        folder=project_path(base,family) if project_path(base,family).is_dir() else base
        manifest=project_path(base,"dataset_manifest.json")
        if manifest.is_file() and folder==base:
            alternatives=[project_path(base,n) for n in ("Krea2","SDXL") if project_path(base,n).is_dir()]
            if not alternatives: raise ValueError("As imagens do manifesto não foram encontradas.")
            folder=alternatives[0]
        project=resources.enter_context(closing(Dataset(dest)))
        rows={}
        if manifest.is_file():
            if manifest.stat().st_size > 128 * 1024**2:
                raise ValueError("Manifesto acima de 128 MiB.")
            rows={r["filename"]:r for r in json.loads(manifest.read_text("utf-8-sig"))["images"]}
        for img in sorted(folder.iterdir()):
            if img.suffix.lower() not in (".png",".jpg",".jpeg",".webp",".bmp"):continue
            img=project_path(folder,img.name)
            side=project_path(folder,img.with_suffix('.txt').name)
            if side.is_file() and side.stat().st_size > 1024**2:
                raise ValueError('TXT excede 1 MiB.')
            key,_=project.import_file(img)
            it=project.items[key]
            row=rows.get(img.name,{})
            for name in ("sdxl","krea","origins","pts_ms","frame_uid","media_uid"):
                if name in row:
                    if name in ("media_uid","frame_uid"):it["origem_"+name]=row[name]
                    else:it[name]=row[name]
            if side.is_file():
                target="krea" if folder.name=="Krea2" else "sdxl" if folder.name=="SDXL" else field(profile)
                it[target]=side.read_text("utf-8-sig").strip()
            it["tags"]=[v.strip() for v in (it.get("sdxl") or "").split(",") if v.strip()]
            it["sdxl_edited"]=bool(it.get("sdxl"))
            it["caption_edited"]=bool(it.get("krea"))
    if not project.items:
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
        with ExitStack() as resources:
            _load_source(source,profile,stage,resources)
        stage.rename(dest)
    return Dataset(dest)
