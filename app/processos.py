"""Processos privados do HydraTrainer encerram junto com a janela que os iniciou."""
import ctypes
from ctypes import wintypes
import os
import socket
import subprocess
import time
import urllib.request

class JobLimit(ctypes.Structure):
    _fields_=[("per_process",ctypes.c_int64),("per_job",ctypes.c_int64),("flags",wintypes.DWORD),
              ("min_ws",ctypes.c_size_t),("max_ws",ctypes.c_size_t),("active",wintypes.DWORD),
              ("affinity",ctypes.c_size_t),("priority",wintypes.DWORD),("scheduling",wintypes.DWORD)]
class Limits(ctypes.Structure):
    _fields_=[("basic",JobLimit),("io",ctypes.c_uint64*6),("memory",ctypes.c_size_t*4)]

if os.name=="nt":
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]

    class Owned:
        def __init__(self,cmd,**kwargs):
            self.job=kernel.CreateJobObjectW(None,None)
            if not self.job:raise ctypes.WinError(ctypes.get_last_error())
            limits=Limits()
            limits.basic.flags=0x2000
            try:
                if not kernel.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.proc=subprocess.Popen(cmd,creationflags=subprocess.CREATE_NO_WINDOW,**kwargs)
                if not kernel.AssignProcessToJobObject(self.job,int(self.proc._handle)):
                    self.proc.kill()
                    raise ctypes.WinError(ctypes.get_last_error())
            except BaseException:
                self.close()
                raise
        def close(self):
            if self.job:
                kernel.CloseHandle(self.job)
                self.job=None
            if hasattr(self,"proc"):
                self.proc.wait(timeout=20)

else:
    class Owned:
        def __init__(self,cmd,**kwargs):
            self.proc=subprocess.Popen(cmd,start_new_session=True,**kwargs)
        def close(self):
            import signal
            try:os.killpg(self.proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            self.proc.wait(timeout=20)

def start_caption(cfg, log, *, thinking=False):
    from pathlib import Path
    for k in ("servidor","modelo_caption","projetor"):
        if not cfg.get(k) or not Path(cfg[k]).is_file():raise ValueError("Configure o componente "+k+" na aba Ambiente.")
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        port=s.getsockname()[1]
    url=f"http://127.0.0.1:{port}"
    cmd=[cfg["servidor"],"-m",cfg["modelo_caption"],"--mmproj",cfg["projetor"],"--host","127.0.0.1","--port",str(port),
         "--alias","hydra-vision","-ngl","99","-c","16384" if thinking else "8192","-np","1","-b","512","-ub","256","-fa","on",
         "-ctk","q8_0","-ctv","q8_0","--image-max-tokens","2048"]
    if thinking:
        pos=cmd.index("-ngl")
        del cmd[pos:pos+2]
        cmd.extend(["--fit","on","--jinja","--reasoning","on","--reasoning-format","deepseek","--reasoning-budget","768"])
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open("w",encoding="utf-8") as f:
        obj=Owned(cmd,cwd=Path(cmd[0]).parent,stdout=f,stderr=subprocess.STDOUT)
    try:
        for _ in range(180):
            if obj.proc.poll() is not None:raise RuntimeError("Modelo de caption encerrou: "+str(log))
            try:
                with urllib.request.urlopen(url+"/health",timeout=2) as rep:
                    if rep.status==200:return obj,url
            except OSError:time.sleep(1)
        raise TimeoutError("O modelo de caption não iniciou. Veja "+str(log))
    except BaseException:
        obj.close()
        raise

