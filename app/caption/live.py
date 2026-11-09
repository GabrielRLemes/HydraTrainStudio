"""Transfer progress and conflict-safe, sequential background captioning."""
from copy import deepcopy
from threading import Lock
from jobs import run_jobs


class Progress:
    def __init__(self):
        self.lock = Lock()
        self.reset("Pronto")

    def reset(self,title):
        with self.lock:
            self.total = self.done = 0
            self.title = title
            self.finished = False
            self.rows = {lane:("Aguardando",0,0,False) for lane in ("download","extract","tags","caption")}

    def plan(self,total):
        with self.lock:self.total = total

    def adjust(self,delta):
        with self.lock:self.total += delta

    def advance(self):
        with self.lock:self.done += 1

    def report(self,lane,label,value,total,complete=False):
        with self.lock:self.rows[lane]=(label,value,total,complete)

    def count(self,lane,label,planned=0,done=0):
        with self.lock:
            _,n,total,_=self.rows[lane]
            n+=done
            total+=planned
            self.rows[lane]=(label,n,total,total>0 and n==total)

    def end(self,success,title):
        with self.lock:
            self.finished=success
            self.title=title
            if not success:
                for lane,(name,value,total,done) in self.rows.items():
                    if not done and name!="Aguardando":
                        self.rows[lane]=(name+" · interrompido",value,total,False)

    def snapshot(self):
        with self.lock:
            return self.title,self.done,self.total,self.finished,self.rows.copy()

class Stage:
    """run_jobs works on an isolated frame while Tk continues to accept edits."""
    def __init__(self,project,key,item):
        self.items={key:deepcopy(item)}
        self.path_for=project.path_for

    def save_one(self,key):
        pass  # The UI thread commits only after checking the live inputs.

def tag_received(ui,key,cfg):
    try:
        for attempt in range(3):
            if ui.stop.is_set():return 0
            def snapshot():
                ui._save_edit()
                return deepcopy(ui.project.items[key]),ui.fit_mode.get(),int(ui.resolution.get())
            before,fit,resolution=ui.on_ui(snapshot)
            if before["status"] not in ("pendente","aprovado") or before.get("tags") or before.get("sdxl_edited"):return 0
            sandbox=Stage(ui.project,key,before)
            item=sandbox.items[key]
            item["ai_resolution"]=resolution
            failed=run_jobs(sandbox,[key],"tags",cfg,"",fit,ui.stop,lambda *_:None,allow_pending=True)
            def commit():
                ui._save_edit()
                live=ui.project.items[key]
                inputs=["status","crop","sdxl","sdxl_edited","tags","inherited_tags"]
                if (ui.stop.is_set() or fit!=ui.fit_mode.get() or resolution!=int(ui.resolution.get())
                        or any(live.get(k)!=before.get(k) for k in inputs)):
                    return False
                live.update({k:v for k,v in item.items() if v!=before.get(k) and k!="caption_stale"})
                ui.project.save_one(key)
                ui.refresh_text(key)
                ui._update_tree(key)
                return True
            if ui.on_ui(commit):return failed
        return 0
    finally:
        if not ui.stop.is_set():ui.progress.count("tags","Imagens sem tags",done=1)
