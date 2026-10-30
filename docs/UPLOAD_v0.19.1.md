# 游织工坊 v0.19.1 上传操作

日期：2026-10-30。目标仓库：`Berserker-Gandalf/game-creation-workbench`。本次是更新已有项目，保留旧标签与附件；不需要新仓库、GitHub Packages 或公开本机服务。

## 要上传什么

本机 `.releases/Questweft-upload-20261030/` 是本次完整操作目录，其 ZIP 可解压后使用。不要把这个总目录或 ZIP 本身上传为源码。

| 目录 | 上传目的地 | 用法 |
| --- | --- | --- |
| `01-source/batch-01` 等 | 仓库 Code 根目录 | 按顺序上传每批目录里面的内容，保留内部路径；不要上传 batch 文件夹本身。每批至多 90 个文件。源码和官网已一起包含，无须再上传旧官网包。 |
| `01-source/manual-files` | GitHub 在线创建/编辑对应路径 | 隐藏文件的正文以普通 TXT 提供，目标路径在 `MANUAL_FILES.tsv` 中。不要上传这些 TXT 或 manual-files 目录。 |
| `02-release-assets` | 新建 v0.19.1 Release 的附件区 | 三个发行文件和各自校验文件，共六个。安装器约 37 MiB，免安装包约 37 MiB，不能拖到 Code 上传区。 |
| `03-after-release/release.json.template` | 确认新版附件可下载后，在线替换 `docs/site/release.json` 正文 | 这是待确认模板，不是已发布记录。核对六个附件名、大小与链接，填实际核验日期后才能使用。 |

`UPLOAD_MANIFEST.json` 记录分批文件与 SHA-256；`CHECKS.json` 记录本机验证。两者在总目录根部供你核对，不需上传为源码。

## 第一步：上传源码和官网

1. 打开 [已有仓库](https://github.com/Berserker-Gandalf/game-creation-workbench)，进入 Code，选择 `main`。推荐先新建 `release/questweft-0.19.1` 分支，再在该分支完成所有上传，避免半套代码触发正式网站更新。
2. 点击 **Add file → Upload files**。打开 `01-source/batch-01`，选中其中所有文件/文件夹拖入。预览路径应为 `backend/...`、`docs/...` 等，不应多出 `batch-01/`。提交这批，再依次上传其余批次。分批之间的 Actions 可能暂时失败，以最后完整提交为准。
3. 打开 `01-source/MANUAL_FILES.tsv`。逐条检查目标文件：已有则用铅笔编辑；缺失则 **Add file → Create new file**，填写完整目标路径，复制对应 TXT 的全部正文。例如 `.github/workflows/ci.yml`、`.gitignore`、`docs/.nojekyll`。已经完全一致的文件可跳过。不要把 Token 写入文件。
4. 浏览器提示 **This file is hidden** 时，使用上述在线编辑方式；若单批上传仍失败，可把该批再分成两次，保持相同目标路径。不要改扩展名后作为源码上传。
5. 确认仓库根目录含 `backend`、`src`、`scripts`、`tests`、`public`、`docs`、`examples`、`media`、锁定依赖与两个 README。`media` 中的历史案例保留原品牌；案例视频不在 `/docs`，网站不展示视频。不要上传 `.dev`、`.workbench`、`.venv`、`node_modules`、`.releases`、`.runtime` 或真实游戏工程。

GitHub 网页每次最多上传 100 个文件、单文件上限 25 MiB；本次分批目录留有余量。[官方说明](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)

## 第二步：看 Actions 再合并

1. 打开 **Actions → Verify workbench**，选择最后一次完整源码提交，核对提交号。
2. `verify (windows-latest)` 和 `verify (ubuntu-latest)` 均应通过：依赖安装、Python 测试、界面构建、网站/小游戏测试、公开文件检查、源码打包。
3. 若分支采用推荐名称，CI 成功后通过 **Compare & pull request** 合并到 `main`；再确认合并提交 CI 通过。已有失败的中间提交无需删除。
4. 若没有此工作流，先核对隐藏文件步骤中的 `.github/workflows/ci.yml`。若需手动重跑，可使用 **Run workflow**，选对分支；它不会自动创建 Release 或部署本机工作台。

## 第三步：发布六个附件

1. 进入 [Releases](https://github.com/Berserker-Gandalf/game-creation-workbench/releases) → **Draft a new release**。
2. 创建新标签 `v0.19.1`，Target 指向上述已验证的 `main` 提交；若该标签已经存在，先核对，不覆盖旧标签。
3. 标题：`v0.19.1 — Questweft · 游织工坊`。正文复制 `docs/RELEASE_NOTES_v0.19.1.md`。勾选 **Set as a pre-release**。
4. 将 `02-release-assets` 中六个文件全部拖入附件区，等待全部传完，再发布：

```text
Questweft-0.19.1-windows-x64-setup.exe
Questweft-0.19.1-windows-x64-setup.exe.sha256
Questweft-0.19.1-windows-x64.zip
Questweft-0.19.1-windows-x64.zip.sha256
game-creation-workbench-0.19.1.zip
game-creation-workbench-0.19.1.zip.sha256
```

GitHub 自动附加的 Source code ZIP/TAR 另计，不代替上述自带界面或 Python 的发行包。**不要把总上传包或官网更新包当作软件附件。** 旧 v0.19.0 Release 与附件保持原样。[官方 Release 操作](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

本次附件来自经审核的本地候选快照，没有声称与尚未产生的 GitHub 提交字节相同。若你在上传过程中改了应用源码，应重新构建发行物，不能沿用这套二进制文件；只完成文档、行尾归一化或下载链接切换不改变应用逻辑，但也应记录差异。上传后可在另行克隆中逐文件核对本次清单，确认附件来源。

## 第四步：切换官网下载与 README

1. 从公开 Release 实际下载上述六个文件，核对文件名/大小。用 PowerShell `Get-FileHash 文件路径 -Algorithm SHA256` 与同名 `.sha256` 的首段比较。只有确认新版附件完整可用才继续。
2. 在线编辑 `docs/site/release.json`：从 `03-after-release/release.json.template` 复制正文，将 `published` 改为 `true`，`verifiedAt` 填实际检查日期（`YYYY-MM-DD`），保留 `appName: "Questweft"`。模板预填的文件名、大小和 URL 仍需与实际附件核对。未发布之前维持当前旧版记录。
3. 同时更新 README.md、README_EN.md 首屏的三个下载及校验链接、版本显示，移除“新版尚未发布”的说明；不要全局替换历史文档中的 v0.19.0。完成后 Actions 应再次通过。
4. **Settings → Pages → Source: Deploy from a branch → Branch: main → Folder: /docs → Save**。保留 `docs/.nojekyll`，等待 **pages build and deployment** 完成。不要将网站来源设为根目录。[官方 Pages 配置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
5. 检查 [正式网站](https://berserker-gandalf.github.io/game-creation-workbench/)：新名称/LOGO，中英文切换，4 个首屏截图和 6 个功能截图，原图预览，动效开关，三类下载和校验入口。强制刷新或无痕窗口核对缓存。网站应不含案例视频入口。
6. 仓库 About 的 Website 设为上述网站；简介和 Topics 可复制 `docs/GITHUB_HOME_PAGE.md`。外部索引与分享缓存的刷新不由本机测试保证。

## 本机验证与限制

验证结果见总目录 `CHECKS.json`。本机测试、打包校验、隔离数据下的自带 Python 启动检查，与远端双系统 CI、干净 Windows 安装、真实付费生成、Unity/Unreal 运行分别验收。安装候选未签名；本轮没有代上传、付费调用、清空数据或扩大 Agent 权限。新版继续使用旧数据路径以保留已有项目与授权，升级前正常停止旧程序并备份。
