"""Geometry and theme helpers shared by the desktop workspaces."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk


def split(parent, orient="horizontal", grid=None):
    """Keep every sash accessible even when the pane minima exceed the viewport."""
    holder=ttk.Frame(parent)
    if grid is None:holder.pack(fill="both",expand=True)
    else:holder.grid(**grid)
    holder.columnconfigure(0,weight=1)
    holder.rowconfigure(0,weight=1)
    view=tk.Canvas(holder,width=1,height=1,borderwidth=0,highlightthickness=0)
    view.grid(row=0,column=0,sticky="nsew")
    horizontal=orient=="horizontal"
    bar=ttk.Scrollbar(holder,orient=orient,command=view.xview if horizontal else view.yview)
    view.configure(**{"xscrollcommand" if horizontal else "yscrollcommand":bar.set})
    work=tk.PanedWindow(view,orient=orient,sashwidth=8,sashrelief="flat",showhandle=True,
                        handlesize=6,borderwidth=0,opaqueresize=True,
                        background=ttk.Style(parent).lookup("TFrame","bordercolor") or "#394353")
    win=view.create_window(0,0,anchor="nw",window=work)
    work.initial_sizes={}
    ratios={}
    last=None
    pending=None
    def remember(_):
        keys=tuple(map(str,work.panes()))
        spans=[work.nametowidget(k).winfo_width() if horizontal else work.nametowidget(k).winfo_height() for k in keys]
        extra=[max(0,s-int(work.panecget(k,"minsize"))) for k,s in zip(keys,spans)]
        if sum(extra):ratios[keys]=extra
    def fit():
        nonlocal pending,last
        pending=None
        if not view.winfo_ismapped():return
        keys=tuple(map(str,work.panes()))
        if not keys:return
        mins=[int(work.panecget(k,"minsize")) for k in keys]
        gap=int(work.cget("sashwidth"))
        minimum=sum(mins)+gap*(len(keys)-1)
        w,h=view.winfo_width(),view.winfo_height()
        available=w if horizontal else h
        if available<minimum:
            bar.grid(row=1 if horizontal else 0,column=0 if horizontal else 1,sticky="ew" if horizontal else "ns")
        else:
            bar.grid_remove()
            if horizontal:view.xview_moveto(0)
            else:view.yview_moveto(0)
        extent=max(available,minimum)
        w,h=(extent,h) if horizontal else (w,extent)
        view.itemconfigure(win,width=w,height=h)
        view.configure(scrollregion=(0,0,w,h))
        if last==(keys,extent):return
        last=keys,extent
        weights=ratios.get(keys) or [max(1,work.initial_sizes[k]-m) for k,m in zip(keys,mins)]
        dimension="width" if horizontal else "height"
        extra=extent-minimum
        sizes=[m+int(extra*weight/sum(weights)) for m,weight in zip(mins,weights)]
        sizes[-1]+=extent-gap*(len(keys)-1)-sum(sizes)
        for key,size in zip(keys,sizes):
            work.paneconfigure(key,**{dimension:size})
    def queue(_=None):
        nonlocal pending
        if pending is None:pending=view.after_idle(fit)
    work.resize_view=queue
    work.bind("<ButtonRelease-1>",lambda e:work.after_idle(remember,e),add="+")
    view.bind("<Configure>",queue)
    view.bind("<Map>",queue)
    return work


def pane(container, minimum, initial, stretch="always"):
    frame=ttk.Frame(container)
    dimension="width" if str(container.cget("orient"))=="horizontal" else "height"
    container.add(frame, minsize=minimum, stretch=stretch, **{dimension:initial})
    container.initial_sizes[str(frame)]=initial
    frame.bind("<Map>",container.resize_view)
    frame.bind("<Unmap>",container.resize_view)
    return frame


def scrolling(host, max_width=None, padding=8, minimum=0):
    """Viewport with a natural-height document; overflowing controls stay reachable."""
    host.rowconfigure(0,weight=1)
    host.columnconfigure(0,weight=1)
    canvas=tk.Canvas(host,width=1,height=1,highlightthickness=0)
    canvas.grid(row=0,column=0,sticky="nsew")
    y=ttk.Scrollbar(host,command=canvas.yview)
    y.grid(row=0,column=1,sticky="ns")
    x=ttk.Scrollbar(host,orient="horizontal",command=canvas.xview)
    canvas.configure(xscrollcommand=x.set,yscrollcommand=y.set)
    sheet=ttk.Frame(canvas)
    sheet.columnconfigure(0,weight=1)
    body=ttk.Frame(sheet,padding=padding)
    body.grid(row=0,column=0,sticky="nsew")
    win=canvas.create_window(0,0,window=sheet,anchor="nw")
    pending=None
    def fit():
        nonlocal pending
        pending=None
        if not canvas.winfo_ismapped():return
        width=canvas.winfo_width()
        needed=max(minimum,body.winfo_reqwidth())
        extent=max(needed,min(width,max_width) if max_width else width)
        canvas.itemconfigure(win,width=extent)
        sheet.rowconfigure(0,minsize=canvas.winfo_height())
        canvas.configure(scrollregion=(0,0,extent,max(sheet.winfo_reqheight(),canvas.winfo_height())))
        if extent>width+1:x.grid(row=1,column=0,sticky="ew")
        else:
            x.grid_remove()
            canvas.xview_moveto(0)
    def queue(_=None):
        nonlocal pending
        if pending is None:pending=canvas.after_idle(fit)
    for widget in (canvas,sheet,body):
        widget.bind("<Configure>",queue,add="+")
        widget.bind("<Map>",queue,add="+")
    body.scroll_canvas=canvas
    root=host.winfo_toplevel()
    if not getattr(root,"page_wheel_bound",False):
        def wheel(event):
            widget=event.widget
            if isinstance(widget,(tk.Text,ttk.Treeview,ttk.Combobox)):return
            step=(-1 if event.num==4 else 1) if event.num in (4,5) else (-1 if event.delta>0 else 1)
            while isinstance(widget,tk.Misc):
                target=getattr(widget,"scroll_canvas",None)
                if target is not None:
                    top,bottom=target.yview()
                    if step<0 and top>0 or step>0 and bottom<1:
                        target.yview_scroll(step,"units");return "break"
                widget=widget.master
        for sequence in ("<MouseWheel>","<Button-4>","<Button-5>"):
            root.bind_all(sequence,wheel,add="+")
        root.page_wheel_bound=True
    return body


def flow(parent,widgets,columns):
    """Reflow from the space actually needed by current translations and fonts."""
    previous=None
    def arrange(_=None):
        nonlocal previous
        width=parent.winfo_width()
        if width<10:return
        count=min(columns,max(1,width//max(w.winfo_reqwidth()+6 for w in widgets)))
        lines=(len(widgets)+count-1)//count
        count=(len(widgets)+lines-1)//lines
        if previous==count:return
        previous=count
        for col in range(columns):
            parent.columnconfigure(col,weight=int(col<count),uniform="cells" if col<count else "")
        for index,w in enumerate(widgets):
            w.grid(row=index//count,column=index%count,padx=2,pady=1,sticky="ew")
    for item in widgets:item.bind("<<ResizeRows>>",lambda _:parent.after_idle(arrange),add="+")
    parent.bind("<Configure>",arrange,add="+")
    parent.bind("<Map>",arrange,add="+")
    for index,item in enumerate(widgets):item.grid(row=0,column=index,sticky="ew")
    parent.after_idle(arrange)


def banner(app):
    head=ttk.Frame(app,padding=(14,3),style="Header.TFrame")
    head.pack(fill="x")
    mark=tk.Canvas(head,width=1,height=52,highlightthickness=0)
    mark.pack(side="left",fill="both",expand=True)
    def draw(_=None):
        dark=app.theme.get()=="Escuro"
        mark.delete("all")
        mark.configure(background="#10131c" if dark else "#eef1f4")
        w,h=mark.winfo_width(),mark.winfo_height()
        for offset,color in ((12,"#222a3c"),(40,"#1b2130"),(61,"#161c27")):
            end=w-offset
            mark.create_polygon(end-h, h,end,0,end+10,0,end+10-h,h,
                                fill=color if dark else "#d6deea",outline="")
        mark.create_image(0,h//2,image=app.assets.image("branding/hydra_symbol_128.png",min(46,h)),anchor="w")
        mark.create_line(55,9,55,h-9,fill="#667185")
        mark.create_image(66,h//2,image=app.assets.image("branding/hydra_wordmark.png",232),anchor="w")
    mark.bind("<Configure>",draw)
    mark.bind("<<ResizeRows>>",draw)
    def compact(event):
        if event.widget is app:
            target=34 if event.height<730 else 52
            if int(mark.cget("height"))!=target:mark.configure(height=target)
    app.bind("<Configure>",compact,add="+")
    app.language_host=ttk.Frame(head,style="Header.TFrame")
    app.language_host.pack(side="right")


def gradient_style(app):
    """A scalable ttk image element keeps keyboard, focus and disabled behavior."""
    style=ttk.Style(app)
    if not hasattr(app,"gradient_images"):
        images=[]
        for low,high in [((116,62,181),(13,115,153)),((133,75,206),(18,128,164)),
                         ((89,52,141),(13,88,117)),((63,66,78),(63,66,78))]:
            im=Image.new("RGBA",(121,32))
            draw=ImageDraw.Draw(im)
            for x in range(im.width):
                rgb=tuple(round(a+(b-a)*x/120) for a,b in zip(low,high))
                draw.line((x,0,x,31),fill=rgb)
            mask=Image.new("L",im.size)
            ImageDraw.Draw(mask).rounded_rectangle((0,0,120,31),radius=7,fill=255)
            im.putalpha(mask)
            images.append(ImageTk.PhotoImage(im,master=app))
        app.gradient_images=images
        style.element_create("Hydra.action","image",images[0],("disabled",images[3]),
                             ("pressed",images[2]),("active",images[1]),border=(59,8,61,8),
                             padding=(8,4),width=1,height=1,sticky="nsew")
    style.layout("Primary.TButton",[("Hydra.action",{"sticky":"nsew","children":[
        ("Button.focus",{"sticky":"nsew","children":[("Button.padding",{"sticky":"nsew","children":[
            ("Button.label",{"sticky":"nsew"})]})]})]})])
