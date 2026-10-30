# Windows 应用与创作工具装配（0.19.1）

本版提供自带 Python 的 Windows x64 ZIP 和图形安装包。基础项目管理不需要先安装 Python、Node 或前端开发工具。AI 服务仍需要本人账号；可选创作工具通过“快速上手”按需装配。

## 安装与启动

1. 下载 `Questweft-0.19.1-windows-x64-setup.exe`，核对同名 `.sha256`。这是未签名的本地安装候选；没有代码签名或已完成干净虚拟机认证的声明。
2. 打开安装包，确认安装后选择推荐位置或其他父目录。安装器新建 `0.19.1` 版本子目录，不覆盖已有目录，不申请管理员权限，不更改系统 Python 或 PATH。开始菜单出现本版启动、停止和安装目录入口。
3. 打开 `Questweft.exe`，浏览器会进入仅本机的工作台。首次进入“快速上手”，可先创建免费练习项目，再配置需要的创作工具。
4. 退出网页不会停止后台服务。使用开始菜单的 `Stop Questweft` 或程序目录内的 `Stop-Workbench.cmd` 正常停止。

也可下载 `Questweft-0.19.1-windows-x64.zip`，完整解压后打开 `Questweft.exe`；不要只复制 EXE。ZIP 包的移动不影响默认用户数据位置。源码 ZIP 仍是另一种发行物，需准备基础开发环境。

自带运行时是官方 CPython 3.13.17 x64 embeddable，基础依赖按 `requirements.lock.txt` 装入私有目录。保留 Python 和依赖各自许可；没有复制 Codex 自带运行时。Windows 的 .NET Framework 4.x 用于图形安装器与启动器（目标为 Windows 10/11 x64）；基础核心可以离线运行，但首次打开可选服务、安装工具和云端生成需要网络。

## 程序、数据与版本

| 内容 | 位置与规则 |
| --- | --- |
| 程序 | 推荐 `%LOCALAPPDATA%/Programs/Questweft/0.19.1`；可另选父目录 |
| 私有 Python | 程序内 `.runtime/python`，不注册系统 Python |
| 用户数据 | 默认 `%LOCALAPPDATA%/ZAOWU/data`；含数据库、工作台资料、日志、独立工具和快照等 |
| 自定义数据 | 仍可设置 `WORKBENCH_DATA` 或使用脚本的 `-DataDirectory` 参数 |
| 源码工作区 | 未带 `packaged.json` 的源码仍默认 `.workbench/`，不会自动迁移旧数据 |

游织工坊 Questweft 为新的展示品牌；`ZAOWU/data` 是为兼容旧版保留的内部数据目录，不会因改名创建一套空数据库。当前公开的 v0.19.0 附件仍使用旧程序名 `ZAOWU.exe`；本文的新文件名适用于 v0.19.1 本地候选及其后续发布。

升级先正常停止旧版、导出工作台资料备份并保存所需工程快照，再安装到新版本目录。安装器拒绝覆盖同名目录，启动器核对版本、实例及数据独占锁。自动更新、数据库降级及自动回滚尚未实现；不要把选择旧程序当成已验证的数据降级。源码旧数据要继续使用时，启动时明确指定原数据目录；移动数据库前先停止服务并备份整个数据目录。

本版是按用户解压安装，尚未登记 Windows“已安装的应用”卸载项。移除前先正常停止服务，再删除所选版本程序目录和该版本开始菜单快捷方式；默认用户数据目录独立保留，需继续留存。不会自动删除真实游戏工程或已有工具。

## 系统目录选择

项目创建、主工程导入、附加来源、WebUI 安装目录、Blender 程序文件、快照备份目录和恢复父目录均有“浏览选择”。Windows 会打开本机目录/文件窗口。取消保留原输入；一次只打开一个窗口，五分钟超时。非 Windows 或图形环境不可用时仍可手填路径。

附加来源可重复点击浏览逐个添加，保留每行一个目录的手工输入；接入仍先扫描预览，合计最多 8 个来源。选择路径不会自动导入、移动资产、执行项目或授予 Agent 新权限。Blender 选择框只列 `blender.exe`，连接保存时仍按原逻辑核验。

## SUNO Skill 完整装配

在“快速上手 → 选择与装配”勾选音乐，点击“查看装配清单”。缺 Node 时先装配 Node，再安装供应方原版 `suno-cn-music` 2.4.0。清单显示来源、固定版本、SHA-256 与目的地；本人审阅后点击“按此清单装配”。

原包仅在用户确认安装时从 [Suno.cn 下载入口](https://mcp.suno.cn/mcp/skill/download) 取得；工作台与 GitHub 发行物不再分发这个第三方包。校验失败、包内容变化、路径异常或目录已有不完整文件均停止，保留原安装；不静默使用新版本，也不运行原包的安装脚本。

工作台管理的 Skill 位于数据目录 `tools/skills/suno-cn-music`。它优先于全局 Skill；尚无管理安装时继续发现原 Codex 全局安装。原始五份文件保持不变，没有修改 helper，不读取、复制或清理账号凭据。不覆盖全局 Skill，不自动升级现有版本。

装配完成后选择项目，进入音乐页，点击现有授权验证按钮。工作台通过原版 `node scripts/suno-client.mjs auth verify` 发起验证，原样交付供应方授权链接；在本人完成网页授权后再次验证，只有服务器返回 `authorized` 才查询账号并允许创作提交。安装文件被发现不等于账号已授权。装配过程没有账户请求、试生成或积分消费。收费提交仍受原有确认和权限控制。

依据：[供应方完整安装规则](https://mcp.suno.cn/mcp/skill/setup.md)。供应方更新原包后需维护者审阅并更新版本/哈希，不能通过取消校验继续安装。

## WebUI 硬件预检

进入“本机绘画”，选择已有目录（或将安装目标设为某个已有目录），在预检面板选择 SD 1.5 / SDXL，填写计划新增下载量后点击“检查硬件与空间”。不要求先启动 WebUI，也不要求先保存有效的 WebUI 配置。

预检只读取系统 RAM、CPU 架构/核心数、显卡与驱动、所选磁盘空间和 WebUI 标识文件。NVIDIA 使用 `nvidia-smi` 的显存总量；不可读时使用 Windows CIM 获取显卡名称与驱动，显存标为未知，不使用会溢出的 32 位 AdapterRAM 推测大显存。单个外部探针有 12 秒上限。不会执行工程脚本、WebUI Python、torch 或模型文件。

本工作台采用保守起步建议：SD 1.5 为 8 GiB 系统内存、4 GiB 显存和 512 分辨率；SDXL 为 16 GiB、8 GiB 和 1024。磁盘预算为新增下载量再加 10 GiB 余量。这些是工作台的建议值，不是供应方承诺的最低配置或兼容性证明；模型、插件、分辨率与后端会改变需求。

达到建议值、未知和需留意分别显示。显存紧张可参考 [WebUI 官方优化说明](https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Optimizations)；AMD/Intel 后端、torch/驱动兼容性和实际出图需另验。预检不自动改启动参数、安装 GPU 库、下载大型权重或接受模型许可。连接 API 与真实出图仍使用原来的独立步骤。

## 构建与验证边界

维护者先执行完整 pytest、`npm run build` 和 `python scripts/check_release.py`，再在 Windows 运行 `python scripts/package_windows.py`。构建器仅收集审阅后的 Git 文件与当前预构建界面，下载固定哈希的官方 Python，取得锁定依赖的 Windows x64 wheel，保留许可并生成逐文件 SHA-256 清单。构建不包括运行数据、账号凭据、音乐原包或第三方游戏。

Python 来源与分发依据：[官方发行目录](https://www.python.org/ftp/python/3.13.17/)、[Windows embeddable 文档](https://docs.python.org/3/using/windows.html#the-embeddable-package)。安装器与启动器源代码在 `scripts/windows/`，由 Windows 自带的 .NET C# 编译器构建，不依赖另一个打包工具的商业许可。

本轮证据、实际执行与未验证项见 [0.19 发布说明](RELEASE_NOTES_v0.19.0.md) 和 [验证记录](verification/setup-v0.19.json)。干净 Windows 虚拟机、签名和各收费服务端到端是独立验收，不用本机隔离启动或模拟测试代替。
