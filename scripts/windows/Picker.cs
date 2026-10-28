using System;
using System.IO;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Picker {
    [STAThread]
    static int Main() {
        Application.EnableVisualStyles();
        string initial = Environment.GetEnvironmentVariable("WORKBENCH_PICK_INITIAL") ?? "";
        string kind = Environment.GetEnvironmentVariable("WORKBENCH_PICK_KIND") ?? "";
        string selected = null;
        using (var owner = new Form()) {
            owner.Text = "ZAOWU - Select a path";
            owner.Width = 360; owner.Height = 100;
            owner.StartPosition = FormStartPosition.CenterScreen;
            owner.TopMost = true;
            owner.Show();
            if (kind == "blender") {
                using (var dialog = new OpenFileDialog()) {
                    dialog.Title = "ZAOWU - Select Blender executable";
                    dialog.Filter = "Blender executable (blender.exe)|blender.exe";
                    if (File.Exists(initial)) dialog.FileName = initial;
                    if (dialog.ShowDialog(owner) == DialogResult.OK) selected = dialog.FileName;
                }
            } else {
                using (var dialog = new FolderBrowserDialog()) {
                    dialog.Description = "ZAOWU - Select a folder / 选择目录";
                    dialog.ShowNewFolderButton = true;
                    if (Directory.Exists(initial)) dialog.SelectedPath = initial;
                    if (dialog.ShowDialog(owner) == DialogResult.OK) selected = dialog.SelectedPath;
                }
            }
            owner.Close();
        }
        Console.WriteLine(new JavaScriptSerializer().Serialize(new {path = selected}));
        return 0;
    }
}
