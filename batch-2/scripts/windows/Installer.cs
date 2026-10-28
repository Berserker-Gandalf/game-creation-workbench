using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Installer {
    // The build supplies this resource. It contains only the reviewed, hashed app payload.
    [STAThread]
    static int Main(string[] args) {
        Application.EnableVisualStyles();
        using (var owner = new Form()) {
        owner.Text = "ZAOWU Setup";
        owner.Width = 360; owner.Height = 100;
        owner.StartPosition = FormStartPosition.CenterScreen;
        owner.TopMost = true;
        owner.Show();
        try {
            if (args.Length != 0) return 2;
            string version;
            using (var reader = new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("version"))) version = reader.ReadToEnd().Trim();
            string parent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "ZAOWU");
            if (MessageBox.Show(owner, "Install ZAOWU " + version + " for this Windows user?\n\nIncludes Python and the built interface. No Python or Node installation is required for core features.\n\nUser data is kept separately in %LOCALAPPDATA%\\ZAOWU\\data. Existing versions and data will be preserved.\n\n安装造物工作台：自带 Python，项目数据独立保留。下一步可选择安装位置。", "ZAOWU Setup", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return 0;
            using (var folder = new FolderBrowserDialog()) {
                folder.Description = "Choose parent folder / 选择安装父目录（将创建版本子目录）";
                folder.SelectedPath = Directory.Exists(parent) ? parent : Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                folder.ShowNewFolderButton = true;
                var choice = MessageBox.Show(owner, "Use recommended location? / 使用推荐安装位置？\n" + parent, "ZAOWU Setup", MessageBoxButtons.YesNoCancel);
                if (choice == DialogResult.No) {
                    if (folder.ShowDialog(owner) != DialogResult.OK) return 0;
                    parent = folder.SelectedPath;
                } else if (choice == DialogResult.Cancel) { return 0; }
            }
            string target = Path.GetFullPath(Path.Combine(parent, version));
            if (Directory.Exists(target) || File.Exists(target)) throw new IOException("This version folder already exists. Choose another parent folder; no files were overwritten.\n版本目录已存在，请选择其他父目录。原数据保留。\n" + target);
            string stage = Path.Combine(parent, ".install-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stage);
            try {
                using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload"))
                using (var zip = new ZipArchive(payload, ZipArchiveMode.Read)) {
                    foreach (var entry in zip.Entries) {
                        string file = Path.GetFullPath(Path.Combine(stage, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                        if (!file.StartsWith(stage + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid package path");
                        Directory.CreateDirectory(Path.GetDirectoryName(file));
                        using (var input = entry.Open()) using (var output = File.Create(file)) input.CopyTo(output);
                    }
                }
                Verify(stage);
                Directory.Move(stage, target);
            } finally {
                string allowed = Path.GetFullPath(parent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                if (Path.GetFullPath(stage).StartsWith(allowed, StringComparison.OrdinalIgnoreCase) && Directory.Exists(stage)) Directory.Delete(stage, true);
            }
            string shortcuts = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "ZAOWU " + version);
            Directory.CreateDirectory(shortcuts);
            Shortcut(Path.Combine(shortcuts, "ZAOWU.lnk"), Path.Combine(target, "ZAOWU.exe"), "", target);
            Shortcut(Path.Combine(shortcuts, "Stop ZAOWU.lnk"), Path.Combine(target, "ZAOWU.exe"), "--stop", target);
            Shortcut(Path.Combine(shortcuts, "Installation folder.lnk"), "explorer.exe", "\"" + target + "\"", target);
            if (MessageBox.Show(owner, "Installed / 安装完成\n" + target + "\n\nOpen ZAOWU now? / 现在打开工作台？", "ZAOWU", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                System.Diagnostics.Process.Start(Path.Combine(target, "ZAOWU.exe"));
            return 0;
        } catch (Exception e) { MessageBox.Show(owner, e.Message, "ZAOWU Setup", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
        }
    }
    static void Shortcut(string path, string executable, string args, string working) {
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic link = shell.CreateShortcut(path);
        link.TargetPath = executable; link.Arguments = args; link.WorkingDirectory = working; link.Save();
    }
    static void Verify(string root) {
        var hashes = new JavaScriptSerializer {MaxJsonLength = 8 * 1024 * 1024}.Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(root, "SHA256SUMS.json")));
        foreach (var item in hashes) {
            string file = Path.GetFullPath(Path.Combine(root, item.Key.Replace('/', Path.DirectorySeparatorChar)));
            if (!file.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid checksum path");
            using (var algorithm = SHA256.Create()) using (var stream = File.OpenRead(file)) {
                string digest = BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                if (digest != item.Value) throw new IOException("Package checksum failed: " + item.Key);
            }
        }
    }
}
