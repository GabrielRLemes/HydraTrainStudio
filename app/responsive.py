import tkinter as tk
from tkinter import ttk
from collections import OrderedDict
from PIL import Image,ImageTk,ImageOps

class Tiles:
    cell=92
    cols=3
    def __init__(self,app,host,tree):
        self.app=app;self.tree=tree;self.anchor=None
        self.cache=OrderedDict();self.pending=None;self.loader=None
        self.canvas=c=tk.Canvas(host,width=168,height=180,highlightthickness=0,takefocus=True)
        bar=ttk.Scrollbar(host,command=c.yview)
        bar.pack(side="right",fill="y");c.pack(fill="both",expand=True)
        def scroll(a,b):
            bar.set(a,b)
            if (a,b)!=getattr(self,"scroll_position",None):
                self.scroll_position=(a,b);self.queue()
        c.configure(yscrollcommand=scroll)
        for event in ("<Configure>","<Map>","<Expose>"):c.bind(event,lambda _:self.queue())
        c.bind("<Button-1>",self.click)
        c.bind("<MouseWheel>",lambda e:(c.yview_scroll(-int(e.delta/120),"units"),"break")[1])
        c.bind("<Delete>",lambda e:app._reject())
        c.bind("<Key>",self.key)
        tree.bind("<<TreeviewSelect>>",lambda _:self.queue(),add="+")
    def queue(self):
        if self.pending is None:self.pending=self.canvas.after_idle(self.draw)
    def draw(self):
        self.pending=None;c=self.canvas
        if not c.winfo_ismapped():return
        ids=self.tree.get_children();self.cols=3;self.cell=max(32,c.winfo_width()//3)
        rows=(len(ids)+self.cols-1)//self.cols
        area=(0,0,self.cols*self.cell,rows*self.cell)
        if getattr(self,"area",None)!=area:
            self.area=area;c.configure(scrollregion=area,yscrollincrement=self.cell)
        c.delete("all");self.visible=[]
        chosen=set(self.tree.selection());first=max(0,int(c.canvasy(0)//self.cell));last=first+c.winfo_height()//self.cell+2
        for index in range(first*self.cols,min(len(ids),last*self.cols)):
            k=ids[index];item=self.app.project.items[k]
            x=(index%self.cols)*self.cell;y=(index//self.cols)*self.cell
            selected=k in chosen
            c.create_rectangle(x+1,y+1,x+self.cell-2,y+self.cell-2,fill="#46515b" if selected else "#343a40",outline="#66bdff" if selected else "#68737c",width=3 if selected else 1)
            path=self.app.project.path_for(item)
            ident=(path,item.get("sha256"),self.cell)
            if ident in self.cache:
                pic=self.cache[ident];self.cache.move_to_end(ident)
                if pic:c.create_image(x+self.cell//2,y+self.cell//2,image=pic);self.visible.append(pic)
                else:c.create_text(x+self.cell//2,y+self.cell//2,text="?",fill="white")
            if self.tree.set(k,"state")=="aprovado":c.create_oval(x+self.cell-18,y+self.cell-18,x+self.cell-9,y+self.cell-9,fill="#58d98c",outline="")
        if self.loader is None:self.loader=c.after(12,self.load_one)
    def load_one(self):
        self.loader=None
        if not self.canvas.winfo_ismapped():return
        ids=self.tree.get_children()
        first=max(0,int(self.canvas.canvasy(0)//self.cell))*self.cols
        count=(self.canvas.winfo_height()//self.cell+2)*self.cols
        for k in ids[first:first+count]:
            it=self.app.project.items[k];path=self.app.project.path_for(it);ident=(path,it.get("sha256"),self.cell)
            if ident in self.cache:continue
            try:
                with Image.open(path) as im:
                    im.draft("RGB",(96,96))
                    small=ImageOps.exif_transpose(im);small.thumbnail((max(24,self.cell-8),)*2,Image.Resampling.LANCZOS)
                    self.cache[ident]=ImageTk.PhotoImage(small)
            except (OSError,ValueError):self.cache[ident]=None
            while len(self.cache)>max(240,count+8):self.cache.popitem(last=False)
            self.queue();break
    def select(self,k,shift,ctrl):
        ids=self.tree.get_children()
        if shift and self.anchor in ids:
            a,b=sorted((ids.index(self.anchor),ids.index(k)))
            if ctrl:self.tree.selection_add(ids[a:b+1])
            else:self.tree.selection_set(ids[a:b+1])
        elif ctrl:self.tree.selection_toggle(k);self.anchor=k
        else:self.tree.selection_set(k);self.anchor=k
        self.tree.focus(k);self.canvas.focus_set();self.app._select();self.queue()
    def click(self,e):
        col=e.x//self.cell
        if col>=self.cols:return
        i=int(self.canvas.canvasy(e.y)//self.cell)*self.cols+col
        ids=self.tree.get_children()
        if 0<=i<len(ids):self.select(ids[i],e.state&1,e.state&4)
    def see(self,k):
        ids=self.tree.get_children()
        if k not in ids or not self.canvas.winfo_ismapped():return
        row=ids.index(k)//self.cols;rows=(len(ids)+self.cols-1)//self.cols
        top=self.canvas.canvasy(0)
        if not top<=row*self.cell<=top+self.canvas.winfo_height()-self.cell:self.canvas.yview_moveto(row/max(1,rows))
    def key(self,e):
        ids=self.tree.get_children()
        if not ids:return
        delta={"Left":-1,"Right":1,"Up":-self.cols,"Down":self.cols}
        if e.keysym not in delta:return
        k=self.tree.focus()
        i=ids.index(k) if k in ids else 0
        k=ids[max(0,min(len(ids)-1,i+delta[e.keysym]))];self.select(k,e.state&1,False);self.see(k);return "break"


def wrap_rows(widget):
    for child in widget.winfo_children():wrap_rows(child)
    if not isinstance(widget,ttk.Frame) or getattr(widget,"fixed_layout",False):return
    controls=widget.pack_slaves()
    if len(controls)<2 or any(c.pack_info()["side"] not in ("left","right") for c in controls):return
    allowed=(ttk.Button,ttk.Checkbutton,ttk.Combobox,ttk.Label,ttk.Entry,ttk.Scale)
    if any(not isinstance(c,allowed) for c in controls):return
    if len(controls)==2 and isinstance(controls[1],ttk.Entry):return
    for c in controls:c.pack_forget()
    for col,c in enumerate(controls):
        c.grid(row=0,column=col,sticky="ew",padx=3,pady=3)
    last=None
    def arrange(event=None):
        nonlocal last
        width=widget.winfo_width()
        if width<40:return
        row=col=used=0;positions=[]
        for c in controls:
            size=min(width,c.winfo_reqwidth()+8)
            if used and used+size>width:row+=1;col=used=0
            positions.append((row,col));used+=size;col+=1
        layout=tuple(positions)
        if layout==last:return
        last=layout
        for c,(r,k) in zip(controls,positions):
            c.grid(row=r,column=k,sticky="ew",padx=3,pady=3)
    widget.bind("<Configure>",arrange,add="+")
    widget.bind("<<ResizeRows>>",arrange,add="+")
    widget.after_idle(arrange)

def notebook_view(app):
    book=ttk.Notebook(app)
    book.pack(fill="both",expand=True,padx=8,pady=3)
    return book
