"""Optional shared media index for projects in the same studio workspace."""
import sqlite3
from pathlib import Path

class Library:
    def __init__(self, folder):
        path=Path(folder)/"indice_compartilhado.sqlite"
        self.db=sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS originals(sha TEXT,md5 TEXT,path TEXT PRIMARY KEY);
            CREATE INDEX IF NOT EXISTS md5_index ON originals(md5);
            CREATE TABLE IF NOT EXISTS visuals(frame TEXT,project TEXT,pixel TEXT,dhash TEXT,band TEXT,
                PRIMARY KEY(frame,project,band));
            CREATE INDEX IF NOT EXISTS pixels_index ON visuals(pixel);
            CREATE INDEX IF NOT EXISTS bands_index ON visuals(band);
        """)

    def original(self,md5):
        for sha,path in self.db.execute("SELECT sha,path FROM originals WHERE md5=?",(md5,)):
            path=Path(path)
            if path.is_file():
                from dataset import file_hash
                if file_hash(path)==sha:return path

    def register(self,row,folder):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO originals VALUES(?,?,?)",(row["sha"],row["md5"],str(folder/row["filename"])))

    def visual(self,key,item,folder):
        from dataset import hamming64
        dhash=item["dhash"]
        other=[]
        for i in (0,4,8,12):
            band=f"{i}:{dhash[i:i+4]}"
            for frame,proj,pixel,d in self.db.execute(
                    "SELECT frame,project,pixel,dhash FROM visuals WHERE band=? AND project<>? LIMIT 80",(band,str(folder))):
                if hamming64(dhash,d)<=5:
                    ref={"project":proj,"frame_uid":frame,"exact":pixel==item["pixel_sha256"]}
                    if ref not in other:other.append(ref)
            self.db.execute("INSERT OR IGNORE INTO visuals VALUES(?,?,?,?,?)",(key,str(folder),item["pixel_sha256"],dhash,band))
        self.db.commit()
        item["shared_matches"]=other

