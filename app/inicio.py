import sys
from pathlib import Path
import traceback
import ctypes
import runpy
from configuracao import DATA
if __name__=="__main__":
    try:
        if sys.platform=="win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HydraTrainStudio.Desktop")
        from studio_shell import log
        log.info("Início HydraTrainStudio")
        runpy.run_path(str(Path(__file__).with_name("hydra.py")),run_name="__main__")
    except Exception as exc:
        file=DATA/"logs/inicializacao.log"
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(traceback.format_exc(),encoding="utf-8")
        if sys.platform!="win32":raise
        ctypes.windll.user32.MessageBoxW(None,f"{exc}\nRegistro: {file}","HydraTrainer",16)

