"""Lightweight desktop and inference-graph checks, without models or GPU."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

args=argparse.ArgumentParser()
args.add_argument("--screenshot",type=Path)
opts=args.parse_args()
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"app"))
with tempfile.TemporaryDirectory() as tmp:
    os.environ["HYDRA_DATA_DIR"]=tmp
    (Path(tmp)/"componentes-apresentados").touch()
    from hydra import Hydra
    from testar import graph
    from componentes import custom_asset
    for family in ("Krea2","Anima","Illustrious"):
        base=graph(family,"","sample",0,42,base="selected.safetensors")["1"]["inputs"]
        assert "selected.safetensors" in base.values()
    assert custom_asset("https://huggingface.co/example/model/resolve/main/test.gguf",".gguf").name=="test.gguf"
    w=Hydra("Studio")
    errors=[]
    def fail(kind,value,tb):
        import traceback
        traceback.print_exception(kind,value,tb)
        errors.append(str(value));w.destroy()
    w.report_callback_exception=fail
    def check():
        if not hasattr(w,"gallery_ui"):
            w.after(100,check);return
        for tab in w.tabs.tabs():
            w.tabs.select(tab);w.update_idletasks()
        w.tabs.select(w.home_page)
        w.workspace_text.set("Studio");w.geometry("1440x900")
        def finish():
            if opts.screenshot:
                import ctypes
                from PIL import ImageGrab
                hwnd=ctypes.windll.user32.GetParent(w.winfo_id())
                ImageGrab.grab(window=hwnd).save(opts.screenshot)
            w.project.close();w.destroy()
        w.after(350,finish)
    w.after(400,check)
    w.after(20000,lambda:(errors.append("Startup timed out"),w.destroy()))
    w.mainloop()
    import logging
    logging.shutdown()
    if errors:raise RuntimeError(errors)
