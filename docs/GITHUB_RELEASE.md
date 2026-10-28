# 上传 GitHub 与发布

适用版本：v0.19.0。源码采用 MIT 许可。本文区分源码上传与应用附件发布；上传源码不会将本机服务部署到公网。

[主页介绍](GITHUB_HOME_PAGE.md)包含中英文 About、Topics 和介绍正文，[上传准备记录](GITHUB_READINESS_2026-10-28.md)记录本轮检查结果。

## 1. 当前状态

本机已有 `main` 分支和审阅后暂存的公开文件，尚无首次提交、Git 作者身份及远端地址。不要重新初始化、清空暂存区或删除运行数据。

源码包括前后端、连接器、测试、脚本、双语首页与手册。`.workbench/`、`.dev/`、`.releases/`、`.runtime/`、依赖环境、凭据、日志和真实游戏工程不进入源码仓库。

## 2. 首次上传

1. 在自己的 GitHub 账号或组织下新建空仓库，建议名 `game-creation-workbench`。不要额外生成 README 或 License。
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

4. 创建首次提交，连接实际仓库地址并推送。下列地址是占位内容，必须替换。

```text
git commit -m "Release v0.19.0 local game creation workbench"
git remote add origin "你的仓库 HTTPS 或 SSH 地址"
git remote -v
git push -u origin main
```

若已有 `origin`，先核对，不覆盖。认证交给 Git Credential Manager 或 SSH，不把 Token 写入 URL、源码或脚本。准备工作没有代替所有者提交或上传。

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
| `ZAOWU-0.19.0-windows-x64-setup.exe` | 是 | 图形安装、开始菜单启动/停止 |
| `ZAOWU-0.19.0-windows-x64.zip` | 是 | 完整解压后打开 `ZAOWU.exe` |
| `game-creation-workbench-0.19.0.zip` | 否 | 源码、锁定依赖与预构建界面 |

各 ZIP 含逐文件 SHA-256。Windows 可用 `Get-FileHash -Algorithm SHA256` 与外部校验文件核对。安装候选未签名；Python 与依赖保留各自许可。原版 SUNO Skill 在用户确认装配时从供应方下载，不随附件分发。安装、数据位置和移除见[应用指南](WINDOWS_APP_AND_SETUP.md)。

## 4. 首次预发布

推送后先等待目标提交的 GitHub Actions。现有配置覆盖 Windows / Ubuntu 的测试、界面构建、公开文件检查与源码打包；本机测试不能代替远端 CI 或 Ubuntu 实机验收。

目标提交通过后创建并推送版本标签：

```text
git tag -a v0.19.0 -m "ZAOWU v0.19.0 prerelease"
git push origin v0.19.0
```

在 Releases 选择该标签，标题使用 `v0.19.0 — Windows app & guided creative tools`，正文复制[本版说明](RELEASE_NOTES_v0.19.0.md)，勾选预发布，上传上述六个文件。GitHub 自动生成的 Source code 归档不含预构建界面或私有解释器，不能代替 Windows 应用附件。

发布前审阅截图与文档，确认只有授权公开的代码、样例和素材。CI、真实服务、引擎运行及干净机器安装分别记录，不宣传为已完成完整双引擎自动开发或多人 SaaS 验收。

## 5. 工作台内发布游戏项目

本文描述工作台自身发行。上传所选游戏项目时，在“项目留存”保存快照、配置仓库、审阅清单后确认上传；它准备独立快照分支，不复制原 Git 历史或覆盖主分支，见[项目留存指南](PROJECT_RETENTION_GUIDE.md)。