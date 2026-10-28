using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class VerifyUnity
{
    public static void Run()
    {
        string root = Directory.GetParent(Application.dataPath).FullName;
        try {
            AssetDatabase.CreateFolder("Assets", "WorkbenchTest");
            var material = new Material(Shader.Find("Standard"));
            material.SetColor("_Color", Color.white);
            AssetDatabase.CreateAsset(material, "Assets/WorkbenchTest/Material.mat");
            var changed = GameWorkbenchBridge.Handle(new GameWorkbenchBridge.Command {
                op = "set_material_color", path = "Assets/WorkbenchTest/Material.mat", name = "_Color", color = new[] { 0.2f, 0.4f, 0.6f, 1f } });
            if (!changed.saved || Math.Abs(material.GetColor("_Color").r - 0.2f) > 0.001) throw new Exception("Color write not verified");
            var restored = GameWorkbenchBridge.Handle(new GameWorkbenchBridge.Command {
                op = "set_material_color", path = changed.path, name = "_Color", color = changed.previous_color });
            if (!restored.saved || Math.Abs(material.GetColor("_Color").r - 1f) > 0.001) throw new Exception("Restore not verified");
            var info = GameWorkbenchBridge.Handle(new GameWorkbenchBridge.Command { op = "inspect", path = changed.path });
            var list = GameWorkbenchBridge.Handle(new GameWorkbenchBridge.Command { op = "list_assets" });
            File.WriteAllText(Path.Combine(root, "verification.json"), "{\"passed\":true,\"version\":\"" + Application.unityVersion + "\",\"checks\":[\"compiled\",\"inspect\",\"material_edit\",\"restore\",\"asset_list\"]}");
            EditorApplication.Exit(0);
        } catch (Exception e) {
            File.WriteAllText(Path.Combine(root, "verification.json"), JsonUtility.ToJson(new GameWorkbenchBridge.Result { error = e.ToString() }));
            EditorApplication.Exit(1);
        }
    }
}
