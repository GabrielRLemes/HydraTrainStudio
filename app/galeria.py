from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from PIL import Image,ImageTk
from configuracao import read_json,write_json,DATA,CONF
from ambiente import LORAS
from comparar import versions,plan
POINTS=(5,3,1)
GUIDE="Escreva um prompt em Conceito e clique em Gerar. Em cada uma das 10 rodadas, compare as imagens anônimas e selecione suas favoritas em ordem. O 1º lugar vale 5 pontos, o 2º vale 3, o 3º vale 1 e os demais valem 0. Com dois checkpoints, escolha apenas dois. Clique novamente para remover uma escolha. Confirme o pódio para avançar. Os nomes e o placar aparecem ao final. Empates em pontos dividem a posição."

def standings(rows,votes):
    scores={r["sha"]:0 for r in rows}
    for ballot in votes.values():
        for sha,points in zip(ballot,POINTS):
            scores[sha]+=points
    return sorted(((scores[r["sha"]],Path(r["arquivo"]).name) for r in rows),key=lambda entry:-entry[0])


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
        self.test_model=tk.StringVar()
        self.model_label=tk.StringVar(value="Padrão do treino")
        frame.columnconfigure(0,weight=1)
        frame.rowconfigure(2,weight=1)
        self.settings_open=tk.BooleanVar(value=True)
        settings=ttk.Frame(frame,padding=6)
        def toggle():
            if self.settings_open.get():settings.grid()
            else:settings.grid_remove()
        ttk.Checkbutton(frame,text="Teste de checkpoints",variable=self.settings_open,command=toggle).grid(row=0,column=0,sticky="w")
        settings.grid(row=1,column=0,sticky="ew")
        self.settings=settings
        row=ttk.Frame(settings);row.pack(fill="x")
        ttk.Button(row,text="Escolher treino…",command=self.choose).pack(side="left")
        ttk.Button(row,text="Reabrir comparação…",command=self.reopen).pack(side="left",padx=5)
        self.run_label=ttk.Label(row);self.run_label.pack(side="left",padx=8)
        base=ttk.Frame(settings);base.pack(fill="x")
        ttk.Button(base,text="Modelo de teste…",command=self.choose_model).pack(side="left")
        ttk.Button(base,text="Restaurar padrão",command=lambda:self.set_model("")).pack(side="left")
        ttk.Label(base,textvariable=self.model_label).pack(side="left",padx=5)
        for title,var in zip(("Conceito","Variação","Sem palavra de ativação"),self.vars):
            row=ttk.Frame(settings);row.pack(fill="x",pady=1)
            ttk.Label(row,text=title,width=20).pack(side="left")
            ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)
        row=ttk.Frame(settings);row.pack(fill="x",pady=3)
        ttk.Label(row,text="Semente").pack(side="left")
        ttk.Entry(row,textvariable=self.seed,width=12).pack(side="left")
        ttk.Label(row,text="Força").pack(side="left",padx=4)
        ttk.Entry(row,textvariable=self.strength,width=6).pack(side="left")
        ttk.Combobox(row,state="readonly",values=("Comparar todas","Teste individual","Ranking (10 rodadas)"),textvariable=self.mode,width=17).pack(side="left",padx=5)
        row=ttk.Frame(settings);row.pack(fill="x",pady=2)
        self.list=ttk.Combobox(row,state="readonly",textvariable=self.pick,width=25);self.list.pack(side="left")
        ttk.Button(row,text="Gerar",command=self.generate).pack(side="left",padx=4)
        ttk.Button(row,text="Retestar favoritas",command=self.retest).pack(side="left")
        ttk.Button(row,text="Completar grade",command=self.resume).pack(side="right")
        area=ttk.LabelFrame(frame,text="Resultados da comparação",padding=6)
        area.grid(row=2,column=0,sticky="nsew")
        self.canvas=tk.Canvas(area,width=1,height=390,highlightthickness=0)
        bar=ttk.Scrollbar(area,command=self.canvas.yview);bar.pack(side="right",fill="y")
        self.canvas.configure(yscrollcommand=bar.set);self.canvas.pack(fill="both",expand=True)
        self.grid=ttk.Frame(self.canvas)
        self.window=self.canvas.create_window((0,0),window=self.grid,anchor="nw")
        self.grid.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.pending_draw=None
        self.signature=None
        def resize(e):
            self.canvas.itemconfigure(self.window,width=e.width)
            if self.pending_draw:self.canvas.after_cancel(self.pending_draw)
            self.pending_draw=self.canvas.after(120,self.resized)
        self.canvas.bind("<Configure>",resize)
        self.photos=[]
        self.draft=[]
        self.ballot_key=None
        self.guide=ttk.Label(settings,text=GUIDE,wraplength=520,justify="left")
        self.guide.bind("<Configure>",lambda e:self.guide.configure(wraplength=max(160,e.width-12)))
        def toggle_guide(*_):
            if self.mode.get()=="Ranking (10 rodadas)":self.guide.pack(fill="x")
            else:self.guide.pack_forget()
        self.mode.trace_add("write",toggle_guide)
    def resized(self):
        self.pending_draw=None
        self.draw()
    def show_results(self):
        self.settings_open.set(False);self.settings.grid_remove()
        self.canvas.yview_moveto(0)
    def set_run(self,run):
        if self.run!=run:self.set_model("")
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
    def set_model(self,path):
        self.test_model.set(path)
        self.model_label.set(Path(path).name if path else self.ui.ui_text("Padrão do treino"))
    def choose_model(self):
        last=read_json(CONF,{}).get("ultima_base_teste")
        path=filedialog.askopenfilename(initialdir=str(Path(last).parent) if last else None,title="Modelo compatível com a família do treino",filetypes=[("SafeTensors","*.safetensors")])
        if path:self.set_model(path)
    def select_place(self,sha,limit):
        if sha in self.draft:self.draft.remove(sha)
        elif len(self.draft)<limit:self.draft.append(sha)
        self.draw()
    def vote(self,j,sha):
        file=self.dest/"votos.json"
        votes=read_json(file,{})
        if str(j) in votes:return
        votes[str(j)]=sha
        write_json(file,votes)
        self.canvas.yview_moveto(0)
        self.draw()
    def generate(self):
        if self.ui.busy:return
        try:
            if not self.run:raise ValueError("Escolha um treino.")
            prompts=[v.get().strip() for v in self.vars if v.get().strip()]
            if not prompts:raise ValueError("Preencha ao menos um prompt.")
            seed=int(self.seed.get()); strength=float(self.strength.get())
            if not (0<=seed<2**63 and 0<strength<=3):raise ValueError("Semente ou força inválidas.")
            ranking=self.mode.get()=="Ranking (10 rodadas)"
            subset=[self.rows[self.list.current()]["sha"]] if self.mode.get()=="Teste individual" else None
            seeds=[seed]*len(prompts)
            if ranking:
                if len(self.rows)<2:raise ValueError("Escolha um treino com pelo menos dois checkpoints distintos.")
                prompt=self.vars[0].get().strip()
                if not prompt:raise ValueError("Preencha o prompt em Conceito.")
                prompts=[prompt]*10
                seeds=[(seed+j)%(2**63) for j in range(10)]
            self.dest=plan(self.run,prompts,seeds,strength,subset,self.test_model.get(),ranking)
            self.show_results();self.resume()
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
                self.set_run(LORAS/m["treino"]);self.dest=dest;self.show_results();self.draw()
                self.set_model(m.get("modelo_teste",m.get("test_model","")))
                self.mode.set("Ranking (10 rodadas)" if m.get("ranking") else "Comparar todas")
                for i,v in enumerate(self.vars):v.set(m["prompts"][i] if i<len(m["prompts"]) and (not m.get("ranking") or i==0) else "")
                self.seed.set(str(m["sementes"][0]));self.strength.set(str(m["forca"]))
            except Exception as e:messagebox.showerror("Abrir grade",str(e))
    def retest(self):
        if self.ui.busy or not self.dest:return
        m=read_json(self.dest/"grade.json")
        if not m["favoritos"]:messagebox.showinfo("Finalistas","Marque ao menos uma versão na grade.");return
        seed=simpledialog.askinteger("Reteste","Nova semente",initialvalue=m["sementes"][0]+1,minvalue=0,maxvalue=2**31-1)
        if seed is not None:
            self.dest=plan(LORAS/m["treino"],m["prompts"],[seed]*len(m["prompts"]),m["forca"],m["favoritos"],m.get("modelo_teste",m.get("test_model","")))
            self.show_results();self.resume()
    def favorite(self,sha):
        if self.ui.busy:
            messagebox.showinfo("Grade","Aguarde a geração ou interrompa para escolher finalistas.");return
        m=read_json(self.dest/"grade.json"); chosen=m["favoritos"]
        if sha in chosen:chosen.remove(sha)
        else:chosen.append(sha)
        write_json(self.dest/"grade.json",m);self.draw()
    def zoom(self,file,title=None):
        win=tk.Toplevel(self.ui);win.title(title or file.name)
        with Image.open(file) as img:
            img.thumbnail((win.winfo_screenwidth()-80,win.winfo_screenheight()-110))
            photo=ImageTk.PhotoImage(img)
        label=ttk.Label(win,image=photo);label.image=photo;label.pack()
    def draw(self):
        if not self.dest:return
        m=read_json(self.dest/"grade.json")
        width=max(180,self.canvas.winfo_width())
        rows=m["versoes"]
        cols=max(1,min(len(rows),width//210))
        size=min(420,max(110,width//cols-28))
        votes=read_json(self.dest/"votos.json",{}) if m.get("ranking") else {}
        podium=m.get("podium_order")
        if self.ballot_key!=(self.dest,len(votes)):
            self.ballot_key=(self.dest,len(votes))
            self.draft=[]
        signature=(tuple(self.draft),self.dest,width,tuple(m["imagens"].items()),tuple(m["favoritos"]),tuple(votes.items()))
        if signature==self.signature:return
        self.signature=signature
        for widget in self.grid.winfo_children():widget.destroy()
        self.photos=[]
        def wheel(event):
            self.canvas.yview_scroll(-int(event.delta/120),"units")
            return "break"
        ranking=m.get("ranking",False)
        if ranking and len(votes)==len(m["prompts"]):
            ttk.Label(self.grid,text="Ranking final").pack(anchor="w")
            if podium:
                previous=None
                for number,(score,name) in enumerate(standings(rows[1:],votes),1):
                    if previous!=score:place=number
                    previous=score
                    ttk.Label(self.grid,text=f"#{place}    {score} pts    ·    {name}").pack(anchor="w")
                return
            counts={r["sha"]:list(votes.values()).count(r["sha"]) for r in rows[1:]}
            for r in sorted(rows[1:],key=lambda r:-counts[r["sha"]]):
                ttk.Label(self.grid,text=f'{counts[r["sha"]]} / {len(votes)}   ·   {Path(r["arquivo"]).name}').pack(anchor="w")
            return
        if ranking:cols=max(1,min(len(rows)-1,width//210))
        for j,prompt in enumerate(m["prompts"]):
            if ranking and j!=len(votes):continue
            if ranking:prompt=f'{j+1} / {len(m["prompts"])}   ·   {prompt}'
            section=ttk.Frame(self.grid);section.pack(fill="x",pady=(4,10))
            heading=ttk.Label(section,text=prompt,wraplength=max(120,width-28),justify="left")
            heading.grid(row=0,column=0,columnspan=cols,sticky="w",padx=5,pady=4)
            for col in range(cols):section.columnconfigure(col,weight=1,uniform="sample")
            indices=podium[j] if podium else range(int(ranking),len(rows))
            if podium:
                ttk.Label(section,text=GUIDE,wraplength=max(160,width-32),justify="left").grid(row=1,column=0,columnspan=cols,sticky="w")
                ready=all((self.dest/m["imagens"].get(f"{i}-{j}","")).is_file() for i in indices)
                if not ready:
                    ttk.Label(section,text="Preparando as imagens da rodada…").grid(row=2,column=0,sticky="w")
                    continue
                limit=min(len(indices),len(POINTS))
                ttk.Button(section,text="Confirmar pódio",state="normal" if len(self.draft)==limit else "disabled",
                           command=lambda j=j:self.vote(j,self.draft.copy())).grid(row=2,column=0,columnspan=cols,sticky="w")
            for index,i in enumerate(indices):
                version=rows[i]
                card=ttk.Frame(section,padding=3)
                card.grid(row=(3 if podium else 1)+index//cols,column=index%cols,sticky="nsew")
                title="Base" if i==0 else f"Passo {version['passo']}"+(" · final" if version["final"] else "")
                if podium:title=f"#{index+1}"
                ttk.Label(card,text=title).pack()
                filename=m["imagens"].get(f"{i}-{j}")
                if filename and (path:=self.dest/filename).is_file():
                    with Image.open(path) as img:
                        img.thumbnail((size,size),Image.Resampling.LANCZOS)
                        photo=ImageTk.PhotoImage(img)
                    self.photos.append(photo)
                    ttk.Button(card,image=photo,padding=1,command=lambda f=path,t=title if podium else None:self.zoom(f,t)).pack()
                else:ttk.Label(card,text="Aguardando").pack()
                if podium:
                    sha=version["sha"]
                    selected=sha in self.draft
                    label=f"★ {self.draft.index(sha)+1}" if selected else "Selecionar"
                    ttk.Button(card,text=label,state="normal" if selected or len(self.draft)<limit else "disabled",
                               command=lambda sha=sha:self.select_place(sha,limit)).pack()
                elif ranking:
                    ready=all((self.dest/m["imagens"].get(f"{k}-{j}","")).is_file() for k in range(1,len(rows)))
                    ttk.Button(card,text="Votar nesta rodada",state="normal" if ready else "disabled",
                               command=lambda sha=version["sha"],j=j:self.vote(j,sha)).pack()
                elif i:
                    label="★ Preferida" if version["sha"] in m["favoritos"] else "Marcar favorita"
                    ttk.Button(card,text=label,command=lambda sha=version["sha"]:self.favorite(sha)).pack(pady=2)
                for child in (card,*card.winfo_children()):child.bind("<MouseWheel>",wheel)
            heading.bind("<MouseWheel>",wheel)
