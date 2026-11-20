using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

class SetupWizard : Form {
    readonly string[] steps = {"Welcome", "Destination", "Training models", "Automatic captions", "Test images", "Shortcuts", "Review", "Installation", "Finish"};
    readonly Color ink = Color.FromArgb(31,38,57), accent = Color.FromArgb(82,60,169);
    readonly Panel sidebar = new Panel(), body = new Panel();
    readonly FlowLayoutPanel content = new FlowLayoutPanel();
    readonly List<Label> navigation = new List<Label>();
    readonly Button back = new Button(), next = new Button(), cancel = new Button();
    readonly Dictionary<string,string> values = new Dictionary<string,string>();
    readonly List<Func<string>> checks = new List<Func<string>>();
    bool installing;

    readonly Label progressText = new Label();
    readonly ProgressBar bar = new ProgressBar();
    int page;
    bool completed;
    string Get(string key,string initial) {
        if(!values.ContainsKey(key)) values[key]=initial;
        return values[key];
    }
    [STAThread] static void Main() {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupWizard());
    }
    public SetupWizard() {
        Text="HydraTrainStudio Setup"; Font=new Font("Segoe UI",10);
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition=FormStartPosition.CenterScreen; MinimumSize=new Size(700,480); Size=new Size(880,620);
        var footer=new FlowLayoutPanel {Dock=DockStyle.Bottom, Height=63, FlowDirection=FlowDirection.RightToLeft, Padding=new Padding(12),BackColor=SystemColors.Control};
        foreach(var b in new[]{cancel,next,back}) { b.Size=new Size(115,33);footer.Controls.Add(b); }
        back.Text="< Back";cancel.Text="Cancel";next.BackColor=accent; next.ForeColor=Color.White;next.FlatStyle=FlatStyle.Flat;
        back.Click+=(s,e)=>{page--;Render();};
        next.Click+=(s,e)=>Advance(); cancel.Click+=(s,e)=>Close();
        AcceptButton=next;CancelButton=cancel;
        sidebar.Dock=DockStyle.Left;sidebar.Width=180;sidebar.BackColor=ink;
        var brand=new Label {Text="HydraTrainStudio",Font=new Font(Font,FontStyle.Bold),ForeColor=Color.White,AutoSize=true,Location=new Point(18,22)};
        sidebar.Controls.Add(brand);
        for(int i=0;i<steps.Length;i++) {
            var label=new Label {Text=steps[i],Location=new Point(12,74+i*31),Size=new Size(158,28),Padding=new Padding(7,3,0,0)};
            sidebar.Controls.Add(label);navigation.Add(label);
        }
        body.Dock=DockStyle.Fill;body.BackColor=Color.White;body.AutoScroll=true;
        content.AutoSize=true; content.FlowDirection=FlowDirection.TopDown;content.WrapContents=false; content.Location=new Point(22,18);
        body.Controls.Add(content);Controls.Add(body);Controls.Add(sidebar);Controls.Add(footer);
        body.Resize+=(s,e)=>Fit();

        FormClosing+=(s,e)=>{if(installing){e.Cancel=true;return;}if(!completed && MessageBox.Show(this,"Close the setup wizard?","Cancel setup",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes)e.Cancel=true;};
        Render();
    }
    void Fit() {
        int w=Math.Max(300,body.ClientSize.Width-65);
        foreach(Control c in content.Controls) {
            var l=c as Label;
            if(l!=null) l.MaximumSize=new Size(w,0);
            else c.Width=w;
            var row=c as FlowLayoutPanel;
            if(row!=null) row.Controls[0].Width=row.Controls.Count==2?w-110:w-8;
        }
    }
    Label Note(string text,bool title=false) {
        var l=new Label {Text=text,AutoSize=true,UseMnemonic=false,ForeColor=ink,Margin=new Padding(0,2,0,title?12:8)};
        if(title)l.Font=new Font(Font.FontFamily,19,FontStyle.Bold);
        content.Controls.Add(l);return l;
    }
    void Choice(string key,params string[] items) {
        var box=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Margin=new Padding(0,0,0,12)};
        box.Items.AddRange(items); box.SelectedItem=Get(key,items[0]);
        box.SelectionChangeCommitted+=(s,e)=>{values[key]=(string)box.SelectedItem;BeginInvoke((Action)Render);};
        content.Controls.Add(box);
    }
    void Input(string key,string label,string initial,string ext,bool folder=false,bool url=false) {
        Note(label);
        var row=new FlowLayoutPanel {Height=36,WrapContents=false,Margin=new Padding(0)};
        var t=new TextBox {Text=Get(key,initial),Margin=new Padding(0,2,5,0)};
        t.TextChanged+=(s,e)=>values[key]=t.Text.Trim();
        row.Controls.Add(t); content.Controls.Add(row);
        if(!url) {
            var pick=new Button {Text="Browse...",Width=90,Height=29,Margin=new Padding(0)};
            pick.Click+=(s,e)=>{
                if(folder){using(var d=new FolderBrowserDialog {Description="Choose the installation folder",ShowNewFolderButton=key=="folder"})if(d.ShowDialog(this)==DialogResult.OK)t.Text=d.SelectedPath;}
                else {using(var d=new OpenFileDialog {Filter="Compatible files|*"+ext,CheckFileExists=true})if(d.ShowDialog(this)==DialogResult.OK)t.Text=d.FileName;}
            };
            row.Controls.Add(pick);
        }
        checks.Add(delegate {
            var v=t.Text.Trim(); Uri u;
            if(url) return Uri.TryCreate(v,UriKind.Absolute,out u)&&u.Scheme=="https"&&u.Host=="huggingface.co"&&u.AbsolutePath.Contains("/resolve/")&&u.AbsolutePath.EndsWith(ext,StringComparison.OrdinalIgnoreCase)?null:"Enter a direct HTTPS Hugging Face file link ending in "+ext+".";
            if(folder) {try {if(Path.IsPathRooted(v)&&Path.GetFullPath(v)==v.TrimEnd('\\') && Path.GetDirectoryName(v)!=null)return null;}catch(ArgumentException){}catch(NotSupportedException){}catch(PathTooLongException){}return "Enter a full installation folder, such as D:\\Apps\\HydraTrainStudio.";}
            return File.Exists(v)&&v.EndsWith(ext,StringComparison.OrdinalIgnoreCase)?null:"Choose an existing "+ext+" file for "+label+".";
        });
    }
    const string download="Download the suggested model",local="Use a model on this PC",link="Use a Hugging Face file link",skip="Set up later";
    readonly string[] families = {"Krea 2 Raw", "Anima Base", "Illustrious XL v0.1"};
    readonly string[] captions = {"Qwen3-VL", "JoyCaption Beta One"};
    bool Selected(string name) {
        return Get("select:"+name, (name==families[0] || name==captions[0]).ToString())=="True";
    }
    void SelectModels(string[] names) {
        foreach(string name in names) {
            var box=new CheckBox { Text=name, Checked=Selected(name), Height=28 };
            box.CheckedChanged+=(s,e)=>{
                values["select:"+name]=box.Checked.ToString();
                BeginInvoke((Action)Render);
            };
            content.Controls.Add(box);
        }
    }
    void Model(string key,string ext,bool optional,bool projector=false) {
        Choice(key,optional?new[]{download,local,link,skip}:new[]{download,local,link});
        var mode=values[key];
        if(mode==local || mode==link) {
            bool remote=mode==link;
            var kind=remote?"URL":"file";
            Input(key+mode,"Model "+kind,"",ext,false,remote);
            if(projector) Input(key+mode+" projector","Matching vision projector "+kind,"",ext,false,remote);
        }
    }
    string Details(string key) {
        var mode=values[key];
        if(mode!=local && mode!=link)return mode;
        string projector;
        return mode+" — "+values[key+mode]+(values.TryGetValue(key+mode+" projector",out projector)?"\nProjector: "+projector:"");
    }
    bool NeedsComfy() {
        return families.Where(Selected).Any(f=>values["test:"+f]!=skip);
    }
    IEnumerable<string> ModelSummary() {
        foreach(var f in families.Where(Selected))yield return "Training — "+f+"\n"+Details(f);
        foreach(var c in captions.Where(Selected))yield return "Automatic captions — "+c+"\n"+Details(c);
        if(!captions.Any(Selected))yield return "Automatic captions — Set up later";
        foreach(var f in families.Where(Selected))yield return "Test images — "+TestName(f)+"\n"+Details("test:"+f);
    }
    string TestName(string family) {return family==families[0]?"Krea 2 Turbo":family;}
    void Shortcut(string key,string label,bool initial) {
        var b=new CheckBox {Text=label,Height=30,Checked=Get(key,initial.ToString())=="True"};
        b.CheckedChanged+=(s,e)=>values[key]=b.Checked.ToString();content.Controls.Add(b);
    }
    void Render() {
        content.SuspendLayout(); while(content.Controls.Count>0){var c=content.Controls[0];content.Controls.Remove(c);if(c!=bar && c!=progressText)c.Dispose();}
        checks.Clear();body.AutoScrollPosition=new Point(0,0);
        for(int i=0;i<steps.Length;i++){navigation[i].ForeColor=i==page?Color.White:Color.LightGray;navigation[i].BackColor=i==page?accent:ink;}
        back.Enabled=page>0&&page<7; next.Enabled=page!=7; next.Text=page==6?"Install":page==8?"Finish":"Next >";cancel.Visible=page!=8;
        switch(page){
        case 0:Note("Welcome to HydraTrainStudio Setup",true);Note("Prepare a Windows workspace to caption images, train a LoRA and compare its checkpoints.");Note("Setup installs Studio and Python for your account. Optional training engines and models may require tens of gigabytes. Review your choices before starting.");Note("Choose Next to begin.");break;
        case 1:Note("Choose an installation folder",true);Note("Setup will create this folder if needed and place Studio, its tools and managed models inside it. In Browse, use New Folder and enter its name. Creating or renaming a folder in the Windows dialog changes it on disk. You may also type a new path below.");Input("folder","Installation folder",Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"HydraTrainStudio"),"",true);break;
        case 2:
            Note("Choose your training models",true);
            Note("Select one or more families. Each uses its own official training weights. Choose a source for each selected base.");
            SelectModels(families);
            Note("Leave all unchecked to install Studio without training weights.");
            foreach(var f in families.Where(Selected)) {Note(f); Model(f,".safetensors",false);}
            break;
        case 3:
            Note("Set up automatic captions",true);
            Note("Choose any vision models you want available for captioning. Leave all unchecked to set up captions later.");
            SelectModels(captions);
            foreach(var c in captions.Where(Selected)) {Note(c); Model(c,".gguf",false,true);}
            break;
        case 4:
            Note("Test your trained LoRAs",true);
            Note("Choose a compatible test model for each training family, or set it up later.");
            foreach(var f in families.Where(Selected)){Note(TestName(f));Model("test:"+f,".safetensors",true);}
            if(!families.Any(Selected))Note("Choose a training family on the Training models page to configure its test model.");
        if(NeedsComfy()){Note("ComfyUI installation");Choice("comfy","Install ComfyUI for Studio","Use an existing ComfyUI folder");if(values["comfy"].StartsWith("Use")){Input("comfyFolder","ComfyUI folder","","",true);checks.Add(()=>File.Exists(Path.Combine(values["comfyFolder"],"main.py")) && new DirectoryInfo(values["comfyFolder"]).Name.Equals("ComfyUI",StringComparison.OrdinalIgnoreCase)?null:"Choose the ComfyUI folder containing main.py.");Input("comfyPython","Python executable for this ComfyUI environment","","python.exe");}}break;
        case 5:Note("Choose how to open Studio",true);Note("Setup will create the selected shortcuts to HydraTrainStudio.exe. You can also open it directly from the installation folder.");Shortcut("start","Create a Start menu shortcut",true);Shortcut("desktop","Create a desktop shortcut",false);break;
        case 6:Note("Review your setup",true);Note("Review your choices. Use Back to make changes, or choose Install to begin.");Note("Installation folder\n"+values["folder"]);foreach(var line in ModelSummary())Note(line);if(NeedsComfy())Note(values["comfy"]+(values["comfy"].StartsWith("Use")?" — "+values["comfyFolder"]:""));Note("Start menu shortcut: "+On("start")+"   •   Desktop shortcut: "+On("desktop"));break;
        case 7:
            Note("Installing HydraTrainStudio",true);
            progressText.Text="Verifying and extracting Studio...";
            progressText.AutoSize=true;content.Controls.Add(progressText);
            bar.Style=ProgressBarStyle.Marquee;content.Controls.Add(bar);
            Note("Keep this window open. Component installation details are written to dados\\logs\\setup.log inside the destination.");
            break;
        case 8:
            completed=true;Note("HydraTrainStudio is ready",true);
            Note("Choose Finish to open Studio. You can also open it directly from:");
            Note(Path.Combine(values["folder"],"HydraTrainStudio.exe"));break;
        }
        content.ResumeLayout();Fit();
    }
    string On(string key){return values[key]=="True"?"Yes":"No";}
    async void Advance() {
        if(installing)return;
        if(page==8){
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(Path.Combine(values["folder"],"HydraTrainStudio.exe")){WorkingDirectory=values["folder"]});Close(); }
            catch(Exception e){MessageBox.Show(this,e.Message,"Could not open Studio");}
            return;
        }
        foreach(var check in checks){var error=check();if(error!=null){MessageBox.Show(this,error,"Check your selection");return;}}
        page++;Render();
        if(page!=7)return;
        installing=true;cancel.Enabled=false;
        try {
            await System.Threading.Tasks.Task.Run(()=>Setup.Install(values, message=>Invoke((Action)(()=>progressText.Text=message))));
            page=8;
        } catch(Exception e){MessageBox.Show(this,e.Message,"Installation interrupted");page=6;}
        finally {installing=false;cancel.Enabled=true;Render();}
    }
}
