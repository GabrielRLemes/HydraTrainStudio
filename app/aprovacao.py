import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk

def work_area(parent):
    if not hasattr(ctypes,"windll"):return parent.winfo_screenwidth(),parent.winfo_screenheight()
    class MonitorInfo(ctypes.Structure):
        _fields_=[("size",wintypes.DWORD),("monitor",wintypes.RECT),("work",wintypes.RECT),("flags",wintypes.DWORD)]
    user=ctypes.windll.user32
    user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]
    user.MonitorFromWindow.restype=wintypes.HANDLE
    user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
    info=MonitorInfo();info.size=ctypes.sizeof(info)
    monitor=user.MonitorFromWindow(parent.winfo_id(),2)
    if monitor and user.GetMonitorInfoW(monitor,ctypes.byref(info)):
        return info.work.right-info.work.left,info.work.bottom-info.work.top
    return parent.winfo_screenwidth(),parent.winfo_screenheight()

def layout_preview(parent,dialog,image,info,caption):
    sw,sh=work_area(parent)
    width=min(720,sw-40,max(400,parent.winfo_width()-32))
    height=min(820,sh-72,max(340,parent.winfo_height()-32))
    dialog.geometry(f"{width}x{height}")
    dialog.minsize(min(width,320),min(height,300))
    dialog.columnconfigure(0,weight=1)
    dialog.rowconfigure(0,weight=3)
    dialog.rowconfigure(2,weight=1)
    canvas=tk.Canvas(dialog,width=1,height=1,highlightthickness=0)
    canvas.grid(row=0,column=0,sticky="nsew",padx=8,pady=4)
    def resize(e):
        shown=image.copy()
        shown.thumbnail((max(1,e.width),max(1,e.height)),Image.Resampling.LANCZOS)
        canvas.photo=ImageTk.PhotoImage(shown)
        canvas.delete("preview")
        canvas.create_image(e.width//2,e.height//2,image=canvas.photo,tags="preview")
    canvas.bind("<Configure>",resize)
    detail=ttk.Label(dialog,text=info,anchor="center",justify="center")
    detail.grid(row=1,column=0,sticky="ew",padx=8)
    detail.bind("<Configure>",lambda e:detail.configure(wraplength=max(1,e.width-4)))
    body=ttk.Frame(dialog)
    body.grid(row=2,column=0,sticky="nsew",padx=8,pady=4)
    editor=tk.Text(body,wrap="word",width=1,height=3,font=parent.cap_text.cget("font"),
                   background=parent.cap_text.cget("background"),foreground=parent.cap_text.cget("foreground"))
    scroll=ttk.Scrollbar(body,command=editor.yview)
    scroll.pack(side="right",fill="y")
    editor.configure(yscrollcommand=scroll.set)
    editor.pack(fill="both",expand=True);editor.insert("1.0",caption);editor.configure(state="disabled")

