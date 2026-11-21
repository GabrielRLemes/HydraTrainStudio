"""Exercise the packaged Bash installer and generated desktop entry on disposable Ubuntu."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tkinter as tk


def until(action,seconds=60):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=action()
        if result:return result
        time.sleep(.25)
    raise RuntimeError("Timed out waiting for the installer or Studio window")


with tempfile.TemporaryDirectory(prefix="Hydra Linux QA ") as tmp:
    root=Path(tmp)
    os.environ.update(HOME=tmp,XDG_DATA_HOME=str(root/"Apps with spaces"))
    client=tk.Tk()
    client.withdraw()
    process=subprocess.Popen(["bash","dist/HydraTrainStudio-Linux.sh"])
    try:
        def wizard():
            if process.poll() is not None:raise RuntimeError("Installer exited before showing the wizard")
            for app in client.tk.splitlist(client.tk.call("winfo","interps")):
                if app!=client.tk.call("tk","appname") and client.tk.call("send",app,"wm title .")=="HydraTrainStudio Setup":
                    return app
        app=until(wizard)
        def send(script):return client.tk.call("send",app,script)
        send("""
            proc findControl {parent label} {
                foreach w [winfo children $parent] {
                    if {![catch {$w cget -text} t] && $t eq $label && [winfo class $w] in {TButton TCheckbutton}} {return $w}
                    set child [findControl $w $label]
                    if {$child ne ""} {return $child}
                }
                return ""
            }
        """)
        def click(label):
            widget=send(("findControl",".",label))
            if not widget:raise RuntimeError("Missing control: "+label)
            send((widget,"invoke"))
        click("Next")
        click("Next")
        click("Krea 2 Raw")
        click("Next")
        click("Qwen3-VL")
        click("Next")
        click("Next")
        click("Next")
        click("Install")
        until(lambda:send(("findControl",".","Open Studio")),480)
        click("Close")
        assert process.wait(timeout=30)==0
        desktop=root/"Apps with spaces/applications/hydratrainstudio.desktop"
        assert desktop.is_file()
        subprocess.run(["desktop-file-validate",str(desktop)],check=True)
        subprocess.run(["gio","launch",str(desktop)],check=True)
        until(lambda:subprocess.run(["xdotool","search","--onlyvisible","--name","^HydraTrainStudio$"],stdout=subprocess.DEVNULL).returncode==0)
    finally:
        if process.poll() is None:process.terminate()
        for log in root.glob("Apps with spaces/HydraTrainStudio/dados/logs/setup-linux.log"):
            print(log.read_text(errors="replace")[-1500:])
        client.destroy()
