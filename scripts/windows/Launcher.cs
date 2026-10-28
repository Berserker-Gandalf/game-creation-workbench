using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher {
    [STAThread]
    static int Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        if (args.Length > 1 || (args.Length == 1 && args[0] != "--stop")) return 2;
        try {
            var info = new ProcessStartInfo(Path.Combine(root, ".runtime", "python", "python.exe"), "-B -X utf8 -m backend.launcher " + (args.Length == 0 ? "start" : "stop"));
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            using (var process = Process.Start(info)) {
                var output = process.StandardOutput.ReadToEndAsync();
                var error = process.StandardError.ReadToEndAsync();
                process.WaitForExit();
                if (process.ExitCode != 0) MessageBox.Show(output.Result + "\n" + error.Result, "ZAOWU - Start / Stop", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return process.ExitCode;
            }
        } catch (Exception e) { MessageBox.Show(e.Message, "ZAOWU", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
    }
}
