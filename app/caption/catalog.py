"""Persistent catalog shared by imports, downloads, frame extraction and review."""
from threading import RLock
import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image
from media import Settings, candidates, inspect
from sources import canonical_tags

def uid(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()

def safe_path(parent, name):
    p = (parent / name).resolve()
    if p.parent != parent.resolve() or Path(name).name != name:
        raise ValueError("Nome de arquivo fora do projeto.")
    return p

def publish(folder, name, write, checksum=None):
    from dataset import file_hash
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as f:
        temp = Path(f.name)
    try:
        write(temp)
        digest = file_hash(temp)
        if checksum and checksum != digest:
            raise ValueError("Conteúdo alterado durante a cópia.")
        dest = safe_path(folder, name)
        while dest.exists():
            if file_hash(dest) == digest:
                return dest
            dest = dest.with_name(dest.stem + "_" + digest[:12] + dest.suffix)
        temp.rename(dest)
        return dest
    finally:
        temp.unlink(missing_ok=True)

def apply_source_tags(item):
    tags=item.get("inherited_tags") or []
    if not tags or item.get("sdxl_edited"):
        return False
    values=dict(tags=list(tags),sdxl=", ".join(tags),tags_ready=True,tags_stale=False,
                tag_origins={tag:"site" for tag in tags},tag_model=None)
    if all(item.get(k)==v for k,v in values.items()):return False
    if item.get("tags")!=tags and item.get("krea"):item["caption_stale"]=True
    item.update(values)
    return True

class Catalog:
    def open_catalog(self):
        self.write_lock=RLock()
        self.progress=lambda *args:None
        self.frame_received=lambda key:None
        self.config_path=self.root/"configuracao.json"
        conf=json.loads(self.config_path.read_text("utf8")) if self.config_path.is_file() else {}
        self.settings = Settings(**conf.get("extrator",{}))
        self.library=None
        if conf.get("biblioteca"):
            from library import Library
            self.library=Library(conf["biblioteca"])
        self.library_folder=conf.get("biblioteca")
        self.auto_extract = True
        self.sidecar_mode = "Ignorar"
        self.stop = None
        self.cache = self.root / "frames"
        self.cache.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "catalogo.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, sha TEXT UNIQUE, md5 TEXT, filename TEXT,
                kind TEXT, duration REAL, origins TEXT);
            CREATE INDEX IF NOT EXISTS media_md5 ON media(md5);
            CREATE TABLE IF NOT EXISTS frames(id TEXT PRIMARY KEY, parent TEXT, pixel TEXT, payload TEXT);
            CREATE INDEX IF NOT EXISTS frame_parent ON frames(parent);
            CREATE INDEX IF NOT EXISTS frame_pixel ON frames(pixel);
            CREATE TABLE IF NOT EXISTS bands(band TEXT, frame TEXT, PRIMARY KEY(band,frame));
            CREATE TABLE IF NOT EXISTS runs(parent TEXT, run TEXT, PRIMARY KEY(parent,run));
            CREATE TABLE IF NOT EXISTS post_refs(source TEXT, post_id TEXT, url TEXT, parent TEXT,
                PRIMARY KEY(source,post_id,url));
            CREATE TABLE IF NOT EXISTS aliases(parent TEXT PRIMARY KEY, frame TEXT);
            CREATE TABLE IF NOT EXISTS parameters(run TEXT PRIMARY KEY,data TEXT);
            CREATE TABLE IF NOT EXISTS stats(data TEXT);
        """)
        self.items = {r["id"]:json.loads(r["payload"]) for r in self.db.execute("SELECT * FROM frames ORDER BY rowid")}
        r = self.db.execute("SELECT data FROM stats").fetchone()
        if r:
            self.counters = json.loads(r[0])
        self.saved = {key:json.dumps(it,ensure_ascii=False) for key,it in self.items.items()}
        migrated = self.root / "projeto.1.0.backup.json"
        if self.path.exists() and not migrated.exists():
            raw = json.loads(self.path.read_text("utf-8"))
            for key, it in raw.get("items", {}).items():
                path = safe_path(self.images, it["filename"])
                if not path.is_file():
                    raise ValueError(f"Original ausente na migração: {path}")
                origin = it["origins"][0]
                new, _ = self.receive(path, origin["source"], origin["post_id"], it.get("tags", []))
                for target in self.children(new):
                    self.items[target].update({k:v for k,v in it.items() if k in (
                        "sdxl","krea","caption_profile","sdxl_edited","crop","status","origins","rating","groups")})
                    self.items[target]["caption_edited"] = bool(it.get("krea"))
                    self.items[target]["tags_ready"] = bool(it.get("sdxl"))
                    self.items[target]["tags"] = canonical_tags(it.get("sdxl","").split(","))
                parent = self.parent(new)
                self.db.execute("UPDATE media SET origins=? WHERE id=?", (json.dumps(it["origins"]),parent))
            self.save()
            shutil.copy2(self.path, migrated)

        # Apply the source-first policy to previous projects without replacing manual edits.
        for key,item in self.items.items():
            if apply_source_tags(item):self.save_one(key)

    def configure_library(self,folder):
        from library import Library
        if self.library:self.library.db.close()
        self.library=Library(folder)
        self.library_folder=str(folder)
        for r in self.db.execute("SELECT * FROM media"):
            self.library.register(r,self.images)
        for key,it in self.items.items():
            self.library.visual(key,it,self.root)
        self.save()
        self.persist_options()

    def persist_options(self):
        from core import atomic_json
        atomic_json(self.config_path,{"extrator":asdict(self.settings),"biblioteca":self.library_folder})

    def close(self):
        if self.library:self.library.db.close()
        self.db.close()

    def save_one(self,key):
        with self.write_lock, self.db:
            it = self.items[key]
            data = json.dumps(it,ensure_ascii=False)
            self.db.execute("INSERT INTO frames VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent=excluded.parent,pixel=excluded.pixel,payload=excluded.payload",(key,it["media_uid"],it["pixel_sha256"],data))
            self.saved[key] = data

    def save(self):
        with self.write_lock, self.db:
            for key, it in self.items.copy().items():
                data = json.dumps(it, ensure_ascii=False)
                if data != self.saved.get(key):
                    self.db.execute("INSERT INTO frames VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent=excluded.parent,pixel=excluded.pixel,payload=excluded.payload",
                                    (key,it["media_uid"],it["pixel_sha256"],data))
                    self.saved[key] = data
            self.db.execute("DELETE FROM stats")
            self.db.execute("INSERT INTO stats VALUES(?)", (json.dumps(self.counters),))

    def save_stats(self):
        with self.write_lock, self.db:
            self.db.execute("DELETE FROM stats")
            self.db.execute("INSERT INTO stats VALUES(?)",(json.dumps(self.counters),))

    def path_for(self, item):
        return safe_path(self.cache if item.get("frame_index") is not None else self.images, item["filename"])

    def parent(self, key):
        return self.items[key]["media_uid"] if key in self.items else key

    def children(self, key):
        parent = self.parent(key)
        return [r[0] for r in self.db.execute("SELECT id FROM frames WHERE parent=?", (parent,))]

    def known(self, post):
        if post.md5:
            r=self.db.execute("SELECT id FROM media WHERE md5=?",(post.md5,)).fetchone()
        else:
            r=self.db.execute("SELECT parent FROM post_refs WHERE source=? AND post_id=? AND url=?",
                              (post.source,post.post_id,post.url)).fetchone()
        if r:
            keys=self.children(r[0])
            return keys[0] if keys else r[0]
        return None

    def merge(self, key, post):
        return self.attach(self.parent(key), self.origin(post))

    @staticmethod
    def origin(post):
        return {**asdict(post),**post.metadata,"url":post.page_url,"file_url":post.url or None,
                "post_url":post.page_url or None,"artist":post.artist or None,"rating":post.rating or None,
                "tags_by_category":post.groups,"all_tags":post.tags,"hash_from_api":post.md5 or None}

    def attach(self, parent, origin):
        row = self.db.execute("SELECT * FROM media WHERE id=?", (parent,)).fetchone()
        origins = json.loads(row["origins"])
        if origin not in origins:
            origins.append(origin)
            with self.write_lock,self.db:
                self.db.execute("UPDATE media SET origins=? WHERE id=?", (json.dumps(origins),parent))
            for key in self.children(parent):
                self.items[key].update(origins=origins, inherited_tags=self.inherited(origins))
                apply_source_tags(self.items[key])
                self.save_one(key)
        self.counters["duplicates"] += 1
        with self.write_lock,self.db:
            self.db.execute("INSERT OR REPLACE INTO post_refs VALUES(?,?,?,?)",(origin["source"],origin["post_id"],origin.get("file_url",""),parent))
        self.save_stats()
        key = self.extract(parent) if self.auto_extract else parent
        return key, "duplicado (origens preservadas)"

    @staticmethod
    def inherited(origins):
        return canonical_tags([t for o in origins for t in o.get("tags",[])])

    def receive(self, src, source, post_id, tags=None, groups=None, rating="", score=None,
                url="", md5="", artist="", post=None):
        from dataset import file_hash, normalize_id
        from sources import Post
        src = Path(src)
        kind, ext, duration = inspect(src,self.settings)
        media_type = {"video":"Vídeos","animation":"GIFs/animações","image":"Imagens"}[kind]
        if source != "Local" and media_type not in getattr(self,"allowed_media",{media_type}):
            raise ValueError("Tipo real fora do filtro: "+media_type)
        sha, actual_md5 = file_hash(src), file_hash(src,"md5")
        if md5 and md5.lower() != actual_md5:
            raise ValueError("Hash diferente do anunciado pela API.")
        post = post or Post(source,str(post_id),"",url,canonical_tags(tags or []),groups or {},md5,score,rating,artist)
        origin = self.origin(post)
        row = self.db.execute("SELECT id FROM media WHERE sha=?", (sha,)).fetchone()
        if row:
            return self.attach(row[0],origin)
        parent = uid(source,str(post_id),sha)
        label = Path(post_id).stem if source == "Local" else source+"_"+str(post_id)
        name = normalize_id(label)[:48]+"_"+parent[:16]+"."+ext
        dest = publish(self.images,name,lambda tmp:shutil.copyfile(src,tmp),sha)
        with self.write_lock, self.db:
            self.db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?)",
                (parent,sha,actual_md5,dest.name,kind,duration,json.dumps([origin])))
            self.db.execute("INSERT OR REPLACE INTO post_refs VALUES(?,?,?,?)",(source,str(post_id),post.url,parent))
        if self.library:self.library.register(self.db.execute("SELECT * FROM media WHERE id=?",(parent,)).fetchone(),self.images)
        self.counters["imported"] += 1
        self.save_stats()
        key = self.extract(parent) if self.auto_extract else parent
        return key, "duplicado (pixels)" if key in self.items and self.parent(key) != parent else "adicionada"

    def import_file(self, path):
        from sources import Post
        path = Path(path).resolve()
        tags, extra = [], {}
        side = path.with_suffix(".txt")
        if self.sidecar_mode != "Ignorar" and side.exists():
            if side.stat().st_size > 1024**2:
                raise ValueError("TXT excede 1 MB.")
            raw = side.read_text("utf-8-sig").strip()
            if self.sidecar_mode == "Tags":
                tags = canonical_tags(raw.split(","))
            else:
                extra["sidecar_caption"] = raw
        post = Post("Local",str(path),"","",tags, metadata=extra)
        return self.receive(path,"Local",str(path),post=post)

    def extract(self,parent):
        try:return self._extract(parent)
        except Exception:
            row=self.db.execute("SELECT filename,kind FROM media WHERE id=?",(parent,)).fetchone()
            if row and row["kind"]!="image":
                self.progress("extract",row["filename"]+" · interrompido",0,None)
            raise

    def _extract(self, parent):
        from dataset import file_hash, image_fingerprint, hamming64
        self.settings.validate()
        row = self.db.execute("SELECT * FROM media WHERE id=?", (parent,)).fetchone()
        path = safe_path(self.images,row["filename"])
        run = uid(parent,asdict(self.settings))
        keys = self.children(parent)
        if self.db.execute("SELECT 1 FROM runs WHERE parent=? AND run=?",(parent,run)).fetchone():
            alias=self.db.execute("SELECT frame FROM aliases WHERE parent=?",(parent,)).fetchone()
            return keys[0] if keys else alias[0] if alias else parent
        origins = json.loads(row["origins"])
        tags = self.inherited(origins)
        if row["kind"] == "image":
            stream = [(None,None,None,{})]
        else:
            stream = candidates(path,row["kind"],row["duration"],self.settings,self.stop,self.progress)
        first = None
        for index, pts, im, metrics in stream:
            key = uid(parent,str(pts),index)
            if key in self.items:
                if run not in self.items[key]["extraction_runs"]:
                    self.items[key]["extraction_runs"].append(run)
                    self.save_one(key)
                first = first or key
                continue
            dest = path
            ms = round(pts*1000) if pts is not None else None
            if im is not None:
                name = f"{path.stem}_t{ms:09}ms_f{index:06}.png"
                dest = publish(self.cache,name,lambda tmp:im.save(tmp,"PNG"))
            pixel, dhash = image_fingerprint(dest)
            twin = self.db.execute("SELECT id FROM frames WHERE pixel=? LIMIT 1",(pixel,)).fetchone()
            with Image.open(dest) as picture:
                color = np.asarray(picture.convert("RGB").resize((1,1))).ravel().tolist()
            bands = [f"{i}:{dhash[i:i+4]}:{int(color[1])//24}" for i in (0,4,8,12)]
            near = []
            for band in bands:
                for (other,) in self.db.execute("SELECT frame FROM bands WHERE band=? LIMIT 64",(band,)):
                    it = self.items[other]
                    if hamming64(dhash,it["dhash"]) <= 5 and other not in near:
                        near.append(other)
            # Keep each frame identity, flag identical pixels; only its canonical copy is pending.
            self.items[key] = dict(media_uid=parent, frame_uid=key, pts_ms=ms, pts=str(pts) if pts is not None else None,
                frame_index=index, extraction_runs=[run], filename=dest.name, sha256=file_hash(dest),
                original_sha256=row["sha"], md5=row["md5"], pixel_sha256=pixel,dhash=dhash,
                near_duplicates=near, duplicate_of=twin[0] if twin else None, origins=origins,
                inherited_tags=tags, tags=[], tags_ready=False, groups={},rating=origins[0].get("rating"),
                sdxl=", ".join(t.replace("_"," ") for t in tags) if index is None else "", krea=(origins[0].get("metadata",{}).get("sidecar_caption") or "") if index is None else "", caption_edited=bool(index is None and origins[0].get("metadata",{}).get("sidecar_caption")), sdxl_edited=False, caption_profile="", status="duplicado" if twin else "pendente",
                crop={"cx":0.5,"cy":0.5,"scale":1.0}, **metrics)
            apply_source_tags(self.items[key])
            # Equivalent static files share the reviewed image and carry both origins.
            if twin and index is None and self.items[twin[0]]["frame_index"] is None:
                del self.items[key]
                self.attach(self.parent(twin[0]),origins[0])
                with self.write_lock,self.db:
                    self.db.execute("INSERT OR REPLACE INTO aliases VALUES(?,?)",(parent,twin[0]))
                first = first or twin[0]
                break
            with self.write_lock,self.db:
                self.db.executemany("INSERT OR IGNORE INTO bands VALUES(?,?)",[(band,key) for band in bands])
            if self.library:
                self.library.visual(key,self.items[key],self.root)
                if any(ref["exact"] for ref in self.items[key]["shared_matches"]):
                    self.items[key]["status"]="duplicado"
            self.save_one(key)
            self.frame_received(key)
            first = first or key
        with self.write_lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO runs VALUES(?,?)",(parent,run))
            self.db.execute("INSERT OR IGNORE INTO parameters VALUES(?,?)",(run,json.dumps(asdict(self.settings))))
        if row["kind"]!="image":self.progress("extract",path.name,1,1,True)
        return first or parent

    def reset(self, delete_files=True):
        tracked={safe_path(self.images,r[0]) for r in self.db.execute("SELECT filename FROM media")}
        tracked.update(self.path_for(it) for it in self.items.values())
        if self.library:
            with self.library.db:
                self.library.db.execute("DELETE FROM visuals WHERE project=?",(str(self.root),))
                self.library.db.executemany("DELETE FROM originals WHERE path=?",[(str(self.images/r[0]),) for r in self.db.execute("SELECT filename FROM media")])
        for table in ("bands","frames","media","runs","stats","aliases","post_refs","parameters"):
            self.db.execute("DELETE FROM "+table)
        self.items.clear()
        self.saved.clear()
        self.counters = {"duplicates":0,"imported":0}
        if delete_files:
            for p in tracked:p.unlink(missing_ok=True)
        self.save()

