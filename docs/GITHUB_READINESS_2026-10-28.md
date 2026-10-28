# GitHub 上传准备记录

日期：2026-10-28。版本：v0.19.0 实验版。范围：工作台自身源码与 Windows 应用候选，不包含用户游戏项目上传。

## 本轮整理

- 统一中文与英文 README：产品定位、创作流程、组件装配、三种下载附件、数据位置和真实验证边界。
- 更新 About 简介、介绍正文、Topics、预发布标题和附件清单，清除“v0.19 没有安装器”等旧表述。
- 上传指南明确本地作者配置、首次提交、远端连接、目标提交与附件对应关系；不预填账号或虚构远端状态。
- `.gitignore` 与公开文件检查排除 `.runtime/`、打包标记、根目录应用 EXE 和生成的哈希清单，防止误提交应用运行时。
- 修正目录选择与 GPU 测试的系统分支，补充非 Windows 不启动 Windows 工具的检查及生成文件排除测试。

## 本机验证

| 检查 | 结果与范围 |
| --- | --- |
| Python 回归 | Windows 本机 215 项通过；不请求真实模型、收费生成或引擎运行 |
| 界面与语言 | TypeScript、双语检查及生产构建通过；2034 条映射、1405 处调用 |
| 构建提示 | 主界面与延迟加载的 3D 模块仍有大于 500 kB 提示，不影响本次构建成功 |
| 公开文件 | 按 Git 清单检查常见凭据、个人绝对路径、运行数据和生成文件；人工审阅仍有必要 |
| 归档 | 重新构建源码 ZIP、Windows ZIP 与安装候选；ZIP 逐文件 SHA-256 及外部校验值核对 |
| Markdown | 核对公开文档本地链接目标，源码与应用附件保持各自清单 |
| 安装历史证据 | 私有 Python、中文/空格路径、隔离图形安装、重启保留数据见[0.19记录](verification/setup-v0.19.json)，其测试数保留当时范围 |

CI 引用已对照官方发行页核对：[checkout](https://github.com/actions/checkout/releases/tag/v7.0.1)、[setup-python](https://github.com/actions/setup-python/releases/tag/v7.1.0)、[setup-node](https://github.com/actions/setup-node/releases/tag/v7.1.0)。工作流保留其 v7 主版本引用，Windows / Ubuntu 矩阵不变。远端尚未运行；本地模拟非 Windows 分支不等于 Ubuntu 实机验收。

## 待所有者完成

1. 确定 GitHub 账号/组织和仓库地址，配置希望公开的 Git 作者姓名与邮箱。
2. 审阅已暂存的公开文件，创建首次提交并推送 `main`。
3. 等待目标提交的远端 CI，通过后重建对应提交的附件，创建 `v0.19.0` 预发布并上传六个文件。

当前 `main` 尚无首次提交，无远端、已上传仓库、远端 CI 结果或已发布 Release。准备完成不代表已经上传。

## 发行物与限制

本机 `.releases/` 中保留 `game-creation-workbench-0.19.0.zip`、`ZAOWU-0.19.0-windows-x64.zip`、`ZAOWU-0.19.0-windows-x64-setup.exe`，各有同名 `.sha256`。附件不提交源码 Git；具体值以本次生成的校验文件为准。

安装候选未签名，干净 Windows 虚拟机、自动升级/数据库回滚、部分真实 API/收费生成、Unity 运行及 GitHub 远端操作仍分别验收。保持本机单用户定位，不作为公网服务部署。

[上传操作](GITHUB_RELEASE.md) · [主页文案](GITHUB_HOME_PAGE.md) · [Windows 使用指南](WINDOWS_APP_AND_SETUP.md)
