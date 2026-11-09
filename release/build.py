"""Build the shared payload and both launchers on a Windows release runner."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import os
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"dist"
OUT.mkdir(exist_ok=True)
repo=os.environ.get("GITHUB_REPOSITORY","")
tag=os.environ.get("GITHUB_REF_NAME","local")
if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+",repo):raise ValueError(repo)
if not re.fullmatch(r"[\w.-]+",tag):raise ValueError(tag)
csc=Path(os.environ["WINDIR"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
def build(source,exe,extra=()):
    subprocess.run([str(csc),"/nologo","/target:winexe","/reference:System.Windows.Forms.dll",
                    "/win32icon:"+str(ROOT/"HydraTrainStudio_Assets/app_icon/HydraTrainStudio.ico"),
                    "/out:"+str(exe),*extra,str(source)],check=True)
with tempfile.TemporaryDirectory() as tmp:
    launcher=Path(tmp)/"HydraTrainStudio.exe"
    build(ROOT/"launcher/HydraTrainer.cs",launcher)
    payload=OUT/"HydraTrainStudio-app.zip"
    with ZipFile(payload,"w",ZIP_DEFLATED) as zip:
        zip.write(launcher,launcher.name)
        for name in ("Abrir.ps1","abrir-linux.sh","componentes.bat","LICENSE","README.md","THIRD_PARTY.md","docs/inicio.png","docs/PUBLICAR.md"):
            zip.write(ROOT/name,name)
        for folder in ("app","HydraTrainStudio_Assets"):
            for path in sorted((ROOT/folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:zip.write(path,path.relative_to(ROOT))
    sha=hashlib.sha256(payload.read_bytes()).hexdigest()
    def render(name):
        return (ROOT/"release"/name).read_text("utf-8-sig").replace("@REPO@",repo).replace("@TAG@",tag).replace("@SHA@",sha)
    cs=Path(tmp)/"Setup.cs";cs.write_text(render("Setup.cs.in"),"utf-8-sig")
    build(cs,OUT/"HydraTrainStudio-Windows.exe",("/reference:System.IO.Compression.dll","/reference:System.IO.Compression.FileSystem.dll"))
    (OUT/"HydraTrainStudio-Linux.sh").write_text(render("linux.sh.in"),encoding="utf8",newline="\n")
files=[payload,OUT/"HydraTrainStudio-Windows.exe",OUT/"HydraTrainStudio-Linux.sh"]
(OUT/"SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in files),"ascii")
