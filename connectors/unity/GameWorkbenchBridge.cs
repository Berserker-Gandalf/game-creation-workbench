// Editor-only bridge. Unity API calls are processed by EditorApplication.update.
using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

[InitializeOnLoad]
public static class GameWorkbenchBridge
{
    [Serializable] public class Command { public string op; public string path; public string name; public float[] color; }
    [Serializable] public class Entry { public string path; public string name; public string type; }
    [Serializable] public class Result {
        public string engine; public string version; public string project_root; public string[] capabilities;
        public string error; public Entry[] assets; public string path; public string name; public string type;
        public string file; public string preview_mode; public bool saved; public float[] previous_color;
        public string backup; public float[] color;
    }
    [Serializable] class Connection { public string engine; public int port; public string token; public string project_root; }
    class Job { public Command command; public TaskCompletionSource<Result> completion = new TaskCompletionSource<Result>(); }
    static readonly ConcurrentQueue<Job> Jobs = new ConcurrentQueue<Job>();
    static HttpListener listener;
    static string token;
    static string Root => Directory.GetParent(Application.dataPath).FullName;

    static GameWorkbenchBridge()
    {
        EditorApplication.update += Drain;
        AssemblyReloadEvents.beforeAssemblyReload += Stop;
        EditorApplication.quitting += Stop;
        EditorApplication.delayCall += Start;
    }

    static void Start()
    {
        if (listener != null || Application.isBatchMode) return;
        try {
            var probe = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
            probe.Start(); int port = ((IPEndPoint)probe.LocalEndpoint).Port; probe.Stop();
            token = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
            listener = new HttpListener(); listener.Prefixes.Add("http://127.0.0.1:" + port + "/"); listener.Start();
            string folder = Path.Combine(Root, "Library/GameWorkbench"); Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder, "connection.json"), JsonUtility.ToJson(new Connection {
                engine = "unity", port = port, token = token, project_root = Root }));
            Task.Run(Listen);
        } catch (Exception e) { Debug.LogWarning("Game Workbench: " + e.Message); Stop(); }
    }

    static async Task Listen()
    {
        var active = listener;
        while (active != null && active.IsListening) {
            try {
                var context = await active.GetContextAsync();
                _ = Task.Run(async () => {
                    try {
                        if (context.Request.HttpMethod != "POST" || context.Request.Url.AbsolutePath != "/command" ||
                            context.Request.Headers["Authorization"] != "Bearer " + token) {
                            context.Response.StatusCode = 403; context.Response.Close(); return;
                        }
                        if (context.Request.ContentLength64 < 1 || context.Request.ContentLength64 > 65536) {
                            context.Response.StatusCode = 413; context.Response.Close(); return;
                        }
                        string raw; using (var reader = new StreamReader(context.Request.InputStream)) raw = await reader.ReadToEndAsync();
                        var job = new Job { command = JsonUtility.FromJson<Command>(raw) }; Jobs.Enqueue(job);
                        var winner = await Task.WhenAny(job.completion.Task, Task.Delay(25000));
                        var result = winner == job.completion.Task ? await job.completion.Task : new Result { error = "Editor busy; inspect result before retrying" };
                        byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(result));
                        context.Response.ContentType = "application/json"; context.Response.ContentLength64 = bytes.Length;
                        await context.Response.OutputStream.WriteAsync(bytes, 0, bytes.Length); context.Response.Close();
                    } catch { try { context.Response.Close(); } catch { } }
                });
            } catch { break; }
        }
    }

    static void Drain()
    {
        if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
        for (int i = 0; i < 8 && Jobs.TryDequeue(out var job); i++) {
            try { job.completion.TrySetResult(Handle(job.command)); }
            catch (Exception e) { job.completion.TrySetResult(new Result { error = e.Message }); }
        }
    }

    public static Result Handle(Command command)
    {
        if (command.op == "status") return new Result { engine = "unity", version = Application.unityVersion,
            project_root = Root, capabilities = new[] { "list_assets", "inspect", "preview", "set_material_color" } };
        if (command.op == "list_assets") {
            var entries = new System.Collections.Generic.List<Entry>();
            foreach (var guid in AssetDatabase.FindAssets("", new[] { "Assets" })) {
                string path = AssetDatabase.GUIDToAssetPath(guid); if (AssetDatabase.IsValidFolder(path)) continue;
                entries.Add(new Entry { path = path, name = Path.GetFileName(path), type = AssetDatabase.GetMainAssetTypeAtPath(path)?.Name });
                if (entries.Count >= 1000) break;
            }
            return new Result { assets = entries.ToArray() };
        }
        if (String.IsNullOrEmpty(command.path) || !command.path.StartsWith("Assets/") || command.path.Contains(".."))
            throw new Exception("Only Assets/ project assets are supported");
        var obj = AssetDatabase.LoadMainAssetAtPath(command.path);
        if (obj == null) throw new Exception("Asset not found");
        if (command.op == "inspect") return new Result { path = command.path, name = obj.name, type = obj.GetType().Name };
        if (command.op == "preview") {
            Texture2D preview = obj as Texture2D;
            if (preview == null) {
                preview = AssetPreview.GetAssetPreview(obj);
                if (preview == null) preview = AssetPreview.GetMiniThumbnail(obj);
            }
            if (preview == null) throw new Exception("No preview available; open this asset in Unity");
            var rt = RenderTexture.GetTemporary(preview.width, preview.height, 0);
            var previous = RenderTexture.active;
            try {
                Graphics.Blit(preview, rt); RenderTexture.active = rt;
                var copy = new Texture2D(preview.width, preview.height, TextureFormat.RGBA32, false);
                copy.ReadPixels(new Rect(0, 0, preview.width, preview.height), 0, 0); copy.Apply();
                string folder = Path.Combine(Root, "Library/GameWorkbench/previews"); Directory.CreateDirectory(folder);
                string file = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".png"); File.WriteAllBytes(file, copy.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(copy);
                return new Result { file = file, preview_mode = obj is Texture2D ? "texture" : "editor_preview_or_icon" };
            } finally { RenderTexture.active = previous; RenderTexture.ReleaseTemporary(rt); }
        }
        if (command.op == "set_material_color") {
            var material = obj as Material;
            if (material == null || String.IsNullOrEmpty(command.name) || !material.HasColor(command.name))
                throw new Exception("Select a material and an existing color property");
            if (command.color == null || command.color.Length != 4 || Array.Exists(command.color, v => v < 0 || v > 1 || Single.IsNaN(v)))
                throw new Exception("RGBA values must be between 0 and 1");
            string folder = "Assets/__WorkbenchBackups"; if (!AssetDatabase.IsValidFolder(folder)) AssetDatabase.CreateFolder("Assets", "__WorkbenchBackups");
            string backup = folder + "/" + Guid.NewGuid().ToString("N") + ".mat";
            if (!AssetDatabase.CopyAsset(command.path, backup)) throw new Exception("Could not create backup");
            Color previous = material.GetColor(command.name); Undo.RecordObject(material, "Game Workbench material color");
            material.SetColor(command.name, new Color(command.color[0], command.color[1], command.color[2], command.color[3]));
            EditorUtility.SetDirty(material); AssetDatabase.SaveAssets();
            return new Result { saved = true, path = command.path, name = command.name, color = command.color,
                previous_color = new[] { previous.r, previous.g, previous.b, previous.a }, backup = backup };
        }
        throw new Exception("Unsupported operation");
    }

    static void Stop() { var active = listener; listener = null; try { active?.Close(); } catch { } }
}
