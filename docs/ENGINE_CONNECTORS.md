# 引擎连接器

连接器是编辑器开发工具，只监听回环地址，通过每次启动生成的令牌认证。不要将其作为运行时游戏组件或开放给局域网/公网。所有编辑器 API 操作都排队到主线程；繁忙或超时后请先查看实际结果，不要盲目重复修改。

## Unreal

1. 先备份工程并关闭编辑器。在工作台创建 Unreal 项目，根目录应包含一个 `.uproject`。
2. 在“模型与引擎”安装连接器。安装会复制 `connectors/unreal/GameWorkbench` 到工程 `Plugins/GameWorkbench`，备份 `.uproject` 并启用工作台、Python Script Plugin 与 Editor Scripting Utilities。
3. 重新打开工程。插件通过 `Content/Python/init_unreal.py` 启动桥接，连接信息在 `Saved/GameWorkbench/connection.json`。
4. 工作台检查连接，扫描资产。在资产详情中读取属性、获取支持的预览，或修改材质实例中已有的 Vector 参数。

已实际验证 Unreal **4.27.2**：贴图导入、属性读取、导出 TGA 后由工作台转换为 PNG、材质实例颜色保存与备份恢复，以及新编辑器进程读回已保存值。尚不能声称所有 UE4/UE5 版本通过。预览不是任意蓝图、关卡或动画渲染器。

材质参数必须已存在，颜色为 RGBA 0–1。修改前在 `/Game/__WorkbenchBackups/` 创建备份；不自动删除这些备份。安装器发现同名连接器时会停止，更新需关闭编辑器并人工比较源码。

卸载：关闭编辑器，移走 `Plugins/GameWorkbench`，从 `.uproject` 移除工作台条目或恢复自己的项目描述备份。仅在确定其他功能不需要时禁用 Python/Editor Scripting。不要删除游戏内容来卸载连接器。

独立验收：`scripts/verify_unreal.py` 和 `scripts/verify_unreal_http.py`。它们会创建测试资产，仅在独立测试工程执行。

## Unity

工程根目录应有 `ProjectSettings/ProjectVersion.txt`。关闭编辑器后安装，会复制 `connectors/unity/GameWorkbenchBridge.cs` 到 `Assets/Editor/`。重新打开工程，等待编译完成，连接信息位于 `Library/GameWorkbench/connection.json`。

源码提供资产列表、序列化属性、可用的编辑器预览及已有材质颜色属性修改。修改前创建 Unity 工程内备份。不支持任意 Shader Graph、场景图或完整模型编辑。

已使用 Unity **6000.5.3f1** 的参考程序集完成独立 C# 编译。当前本机未激活许可证，编辑器以退出码 198 终止，**运行验证尚未通过**。激活后应先在独立工程执行 `scripts/VerifyUnity.cs` 中的 `VerifyUnity.Run`，再验证工作台桥接、保存后关闭重开和资源引用。

卸载：关闭编辑器，移走 `Assets/Editor/GameWorkbenchBridge.cs` 及其 Unity 生成的对应 `.meta`，然后重开。运行期连接信息会被下一次桥接启动替换，不需要复制到其他电脑。
