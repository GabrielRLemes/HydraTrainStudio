from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from PIL import Image,ImageTk
from configuracao import read_json,write_json,DATA,CONF
from ambiente import LORAS
from comparar import versions,plan
import sys

class Gallery:
    def __init__(self,ui,frame):
        self.ui=ui
        self.run=None
        self.dest=None
        self.frame=frame
        self.vars=[tk.StringVar(value=s) for s in ("", "", "")]
        self.seed=tk.StringVar(value="42")
        self.strength=tk.StringVar(value="0.85")
        self.mode=tk.StringVar(value="Comparar todas")
        self.pick=tk.StringVar()
        frame.columnconfigure(0,weight=38,uniform="test");frame.columnconfigure(1,weight=62,uniform="test")
        frame.rowconfigure(0,weight=1)
        settings=ttk.LabelFrame(frame,text="Teste de checkpoints",padding=10)
        settings.grid(row=0,column=0,sticky="nsew",padx=(0,6))
        row=ttk.Frame(settings);row.pack(fill="x")
        ttk.Button(row,text="Escolher treino…",command=self.choose).pack(side="left")
        ttk.Button(row,text="Reabrir comparação…",command=self.reopen).pack(side="left",padx=5)
        self.run_label=ttk.Label(row);self.run_label.pack(side="left",padx=8)
        self.test_base=tk.StringVar()
        ttk.Button(settings,text="Escolher base de teste…",command=self.choose_base).pack(anchor="w")
        ttk.Label(settings,textvariable=self.test_base,wraplength=300).pack(anchor="w")
        ttk.Button(settings,text="Usar base padrão",command=lambda:self.test_base.set("")).pack(anchor="w")
        for title,var in zip(("Conceito","Variação","Sem palavra de ativação"),self.vars):
            row=ttk.Frame(settings);row.pack(fill="x",pady=1)
            ttk.Label(row,text=title,width=20).pack(side="left")
            ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)
        row=ttk.Frame(settings);row.pack(fill="x",pady=3)
        ttk.Label(row,text="Semente").pack(side="left")
        ttk.Entry(row,textvariable=self.seed,width=12).pack(side="left")
        ttk.Label(row,text="Força").pack(side="left",padx=4)
        ttk.Entry(row,textvariable=self.strength,width=6).pack(side="left")
        ttk.Combobox(row,state="readonly",values=("Comparar todas","Teste individual"),textvariable=self.mode,width=17).pack(side="left",padx=5)
        row=ttk.Frame(settings);row.pack(fill="x",pady=2)
        self.list=ttk.Combobox(row,state="readonly",textvariable=self.pick,width=25);self.list.pack(side="left")
        ttk.Button(row,text="Gerar",command=self.generate).pack(side="left",padx=4)
        ttk.Button(row,text="Retestar favoritas",command=self.retest).pack(side="left")
        ttk.Button(row,text="Completar grade",command=self.resume).pack(side="right")
        area=ttk.LabelFrame(frame,text="Resultados da comparação",padding=8);area.grid(row=0,column=1,sticky="nsew",padx=(6,0))
        self.canvas=tk.Canvas(area,highlightthickness=0)
        bar=ttk.Scrollbar(area,command=self.canvas.yview)
        bar.pack(side="right",fill="y")
        horizontal=ttk.Scrollbar(area,orient="horizontal",command=self.canvas.xview);horizontal.pack(side="bottom",fill="x")
        self.canvas.configure(yscrollcommand=bar.set,xscrollcommand=horizontal.set);self.canvas.pack(fill="both",expand=True)
        self.grid=ttk.Frame(self.canvas);self.canvas.create_window((0,0),window=self.grid,anchor="nw")
        self.grid.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.photos=[]
    def choose_base(self):
        last=read_json(CONF,{}).get("ultima_base_teste")
        path=filedialog.askopenfilename(initialdir=str(Path(last).parent) if last else None,title="Base de teste compatível com a família do treino",filetypes=[("Safetensors","*.safetensors")])
        if path:self.test_base.set(path)
    def set_run(self,run):
        if self.run!=run:self.test_base.set("")
        rows=versions(run)
        if not rows:raise ValueError("Pasta sem LoRAs deste treino.")
        self.run=run
        self.rows=rows
        self.list.configure(values=[Path(r["arquivo"]).name for r in rows])
        self.list.current(len(rows)-1)
        self.run_label.configure(text=run.name)
    def choose(self):
        folder=filedialog.askdirectory(initialdir=LORAS,title="Pasta de uma execução de treino")
        if folder:
            try:self.set_run(Path(folder))
            except Exception as e:messagebox.showerror("Treino",str(e))
    def generate(self):
        if self.ui.busy:return
        try:
            if not self.run:raise ValueError("Escolha um treino.")
            prompts=[v.get().strip() for v in self.vars if v.get().strip()]
            if not prompts:raise ValueError("Preencha ao menos um prompt.")
            seed=int(self.seed.get()); strength=float(self.strength.get())
            if not (0<=seed<2**63 and 0<strength<=3):raise ValueError("Semente ou força inválidas.")
            subset=None if self.mode.get()=="Comparar todas" else [self.rows[self.list.current()]["sha"]]
            self.dest=plan(self.run,prompts,[seed]*len(prompts),strength,subset,self.test_base.get())
            self.resume()
        except Exception as e:messagebox.showerror("Comparação",str(e))
    def resume(self):
        if self.ui.busy or not self.dest:return
        self.draw()
        self.ui.execute("Comparando LoRAs","comparar.py",[str(self.dest)],self.draw)
    def reopen(self):
        f=filedialog.askopenfilename(initialdir=DATA/"comparacoes",filetypes=[("Grade","grade.json")])
        if f:
            try:
                dest=Path(f).parent
                m=read_json(dest/"grade.json")
                self.set_run(LORAS/m["treino"]);self.dest=dest;self.test_base.set(m.get("modelo_teste",""));self.draw()
                for i,v in enumerate(self.vars):v.set(m["prompts"][i] if i<len(m["prompts"]) else "")
                self.seed.set(str(m["sementes"][0]));self.strength.set(str(m["forca"]))
            except Exception as e:messagebox.showerror("Abrir grade",str(e))
    def retest(self):
        if self.ui.busy or not self.dest:return
        m=read_json(self.dest/"grade.json")
        if not m["favoritos"]:messagebox.showinfo("Finalistas","Marque ao menos uma versão na grade.");return
        seed=simpledialog.askinteger("Reteste","Nova semente",initialvalue=m["sementes"][0]+1,minvalue=0,maxvalue=2**31-1)
        if seed is not None:
            self.dest=plan(LORAS/m["treino"],m["prompts"],[seed]*len(m["prompts"]),m["forca"],m["favoritos"],m.get("modelo_teste"))
            self.resume()
    def favorite(self,sha):
        if self.ui.busy:
            messagebox.showinfo("Grade","Aguarde a geração ou interrompa para escolher finalistas.");return
        m=read_json(self.dest/"grade.json"); chosen=m["favoritos"]
        if sha in chosen:chosen.remove(sha)
        else:chosen.append(sha)
        write_json(self.dest/"grade.json",m);self.draw()
    def zoom(self,file):
        win=tk.Toplevel(self.ui);win.title(file.name)
        with Image.open(file) as img:
            img.thumbnail((win.winfo_screenwidth()-80,win.winfo_screenheight()-110))
            photo=ImageTk.PhotoImage(img)
        label=ttk.Label(win,image=photo);label.image=photo;label.pack()
    def draw(self):
        if not self.dest:return
        m=read_json(self.dest/"grade.json")
        for w in self.grid.winfo_children():w.destroy()
        self.photos=[]
        for j,p in enumerate(m["prompts"]):ttk.Label(self.grid,text=p,wraplength=175).grid(row=0,column=j+1,padx=4)
        for i,r in enumerate(m["versoes"]):
            title="Base" if not i else f"Passo {r['passo']}"+(" · final" if r["final"] else "")
            cell=ttk.Frame(self.grid);cell.grid(row=i+1,column=0,padx=8)
            ttk.Label(cell,text=title).pack()
            if i:ttk.Button(cell,text="★ Preferida" if r["sha"] in m["favoritos"] else "Marcar favorita",
                            command=lambda s=r["sha"]:self.favorite(s)).pack()
            for j in range(len(m["prompts"])):
                filename=m["imagens"].get(f"{i}-{j}")
                if filename and (f:=self.dest/filename).is_file():
                    with Image.open(f) as img:
                        img.thumbnail((170,170));photo=ImageTk.PhotoImage(img)
                    self.photos.append(photo)
                    ttk.Button(self.grid,image=photo,command=lambda file=f:self.zoom(file)).grid(row=i+1,column=j+1)
                else:ttk.Label(self.grid,text="Aguardando").grid(row=i+1,column=j+1)

