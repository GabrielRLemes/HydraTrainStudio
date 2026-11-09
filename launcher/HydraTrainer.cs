using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
internal static class HydraTrainer {
    [STAThread] private static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try {
            string script = Path.Combine(root, "Abrir.ps1");
            if (!File.Exists(script)) throw new IOException("Extraia todo o ZIP antes de abrir o HydraTrainer.");
            var cmd = new ProcessStartInfo("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"");
            cmd.WorkingDirectory = root;
            cmd.UseShellExecute = false;
            cmd.CreateNoWindow = true;
            Process.Start(cmd);
        } catch (Exception e) { MessageBox.Show(e.Message, "HydraTrainStudio"); }
    }
}

