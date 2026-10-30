# 上传 GitHub 与发布

适用版本：v0.19.1。源码采用 MIT 许可。本文区分源码上传与应用附件发布；上传源码不会将本机服务部署到公网。

[主页介绍](GITHUB_HOME_PAGE.md)包含中英文 About、Topics 和介绍正文。[本次上传操作](UPLOAD_v0.19.1.md)列出源码分批上传、隐藏文件、六个发行附件及官网切换步骤；2026-10-28 的上传准备记录属于历史版本。

## 1. 当前状态

截至 2026-10-30，本机已有 `main` 分支、v0.19.0 基线提交及指向 `Berserker-Gandalf/game-creation-workbench` 的 `origin`，本轮更名改动尚待提交/上传。远端此前由网页上传，不能假定本地与远端提交历史相同。不要重新初始化、清空暂存区、强制推送或删除运行数据。

源码包括前后端、连接器、测试、脚本、双语首页与手册。`.workbench/`、`.dev/`、`.releases/`、`.runtime/`、依赖环境、凭据、日志和真实游戏工程不进入源码仓库。

## 2. 更新已有仓库

1. 打开已有仓库，不需要另建仓库。网页上传按[本次上传操作](UPLOAD_v0.19.1.md)执行；以下为使用 Git 的备选流程。
2. 检查已暂存清单；新增文件逐项加入，不盲目上传整个工作目录。

```text
git status --short
git diff --cached --stat
python -X utf8 scripts/check_release.py
```

3. 配置本人希望公开的提交姓名和邮箱。替换下列两个值；只设置本仓库，不改全局配置。

```text
git config user.name "你的 Git 提交姓名"
git config user.email "你的 GitHub noreply 邮箱或提交邮箱"
git var GIT_AUTHOR_IDENT
```

4. 由于本地与网页提交历史可能不同，建议将远端另行克隆到一个新的空目录，复制审核后的源码文件（包含需要的隐藏文件），在该克隆中确认差异、测试和提交。不要把本机 `.git`、运行数据或发行目录复制进去。以下命令在新的克隆中执行：

```text
git commit -m "Rebrand workbench as Questweft v0.19.1"
git remote -v
git push origin main
```

先核对新克隆的 `origin`、目标分支及差异；推送被拒绝时先同步远端，不使用强推。认证交给 Git Credential Manager 或 SSH，不把 Token 写入 URL、源码或脚本。本次准备没有代替所有者提交或上传。

## 3. 验证与打包

```text
python -X utf8 -m pytest -q
npm run build
python -X utf8 scripts/check_release.py
python -X utf8 scripts/package_release.py
```

Windows 构建主机额外运行：

```text
python -X utf8 scripts/package_windows.py
```

打包器读取 Git 已跟踪/已暂存文件在工作区中的内容及当前 `dist/`，不是自动读取某个提交快照。正式发布应先完成目标提交，确认 `git diff --exit-code` 和 `git diff --cached --exit-code` 均无改动，再重新构建打包，使附件对应目标提交。

`.releases/` 内应有三种发行物及三个同名 `.sha256` 文件：

| 发行物 | 自带 Python | 用途 |
| --- | --- | --- |
| `Questweft-0.19.1-windows-x64-setup.exe` | 是 | 图形安装、开始菜单启动/停止 |
| `Questweft-0.19.1-windows-x64.zip` | 是 | 完整解压后打开 `Questweft.exe` |
| `game-creation-workbench-0.19.1.zip` | 否 | 源码、锁定依赖与预构建界面 |

各 ZIP 含逐文件 SHA-256。Windows 可用 `Get-FileHash -Algorithm SHA256` 与外部校验文件核对。安装候选未签名；Python 与依赖保留各自许可。原版 SUNO Skill 在用户确认装配时从供应方下载，不随附件分发。安装、数据位置和移除见[应用指南](WINDOWS_APP_AND_SETUP.md)。

## 4. 品牌更新预发布

推送后先等待目标提交的 GitHub Actions。现有配置覆盖 Windows / Ubuntu 的测试、界面构建、公开文件检查与源码打包；本机测试不能代替远端 CI 或 Ubuntu 实机验收。

已有的 v0.19.0 标签与旧品牌附件保留，不覆盖或强推。目标提交通过后，为本版本创建并推送新标签：

```text
git tag -a v0.19.1 -m "Questweft v0.19.1 prerelease"
git push origin v0.19.1
```

在 Releases 选择该标签，标题使用 `v0.19.1 — Windows app & guided creative tools`，正文复制[本版说明](RELEASE_NOTES_v0.19.1.md)，勾选预发布，上传上述六个文件。GitHub 自动生成的 Source code 归档不含预构建界面或私有解释器，不能代替 Windows 应用附件。

发布前审阅截图与文档，确认只有授权公开的代码、样例和素材。CI、真实服务、引擎运行及干净机器安装分别记录，不宣传为已完成完整双引擎自动开发或多人 SaaS 验收。

## 5. 工作台内发布游戏项目

本文描述工作台自身发行。上传所选游戏项目时，在“项目留存”保存快照、配置仓库、审阅清单后确认上传；它准备独立快照分支，不复制原 Git 历史或覆盖主分支，见[项目留存指南](PROJECT_RETENTION_GUIDE.md)。
