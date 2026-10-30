# GitHub 主页介绍

当前源码：v0.19.1 品牌更新候选；公开下载：旧品牌 v0.19.0。日期：2026-10-29。以下文案可直接用于仓库首页、About 和首次预发布；仓库地址与远端 CI 状态在上传后确认。

## 仓库与首页

建议仓库名：`game-creation-workbench`。品牌名：**游织工坊 · Questweft**。

[README.md](../README.md) 是中文版首页，[README_EN.md](../README_EN.md) 是英文版，包含标志、截图、创作流程、能力、安装与验证边界。About 的 Website 使用 `https://berserker-gandalf.github.io/game-creation-workbench/`。该站为介绍与下载页，工作台仍在本机运行。

## About 简介

中文：

游织工坊 Questweft：开源、本地运行的 AI 独立游戏制作工作台。接续 Unreal / Unity 工程，连接对话、美术、音乐和建模工具，管理任务、资产版本、上下文与项目快照。支持中文 / English，提供自带 Python 的 Windows 安装候选。

English:

Questweft: an open-source, local AI indie game development workbench. Connect Unreal/Unity projects and creative tools; manage conversations, versioned assets, tasks and snapshots. Chinese/English UI, with a Windows app candidate.

## 主页介绍正文

**游织工坊（Questweft）把游戏设计、AI 创作与项目交付放在同一个本地工作空间。**

你可以接入已有的 Unreal Engine 或 Unity 工程，以及独立的美术、音频和设计资料目录，从当前进度继续创作。项目总负责人、音乐负责人和建模负责人分别维护会话与工作范围，帮助讨论设计、记录决策、准备创作方案和反馈项目状态。

工作台连接 Codex 会员、本机官方 App Server 与 OpenAI / DeepSeek API，并提供 WebUI、Blender、Suno.cn Skill 和 Tripo 接入。模型与推理强度可按服务能力选择；项目资料、历史回查和 Markdown 留存让工作能够接续。创作产出可纳入版本化资产，关联具体任务、文件哈希与验收记录，再通过工程快照、独立恢复和 GitHub 发布准备进行留存。

v0.19 提供自带 Python 的 Windows x64 安装候选、系统目录选择、原版 SUNO Skill 装配和 WebUI 硬件预检。没有 AI 账号也能先使用项目管理。修改权限、整机访问和自动积分消费分别控制，收费结果未知时不自动重提。

当前是 Windows 优先、本机单用户的实验版，支持简体中文与英文，源码采用 MIT 许可。部分真实服务和引擎流程仍待独立验收，完整范围在仓库文档中公开记录。

## Topics

`game-development`, `indie-game-development`, `ai-game-development`, `game-design`, `ai-agents`, `project-management`, `unreal-engine`, `unity`, `blender`, `stable-diffusion`, `mcp`, `react`, `fastapi`, `local-first`, `generative-ai`

Topics 描述接入方向，不表示官方背书。

## 已公开的历史预览版（保留文件名）

标题：`v0.19.0 — Windows app & guided creative tools`

正文：[v0.19 发布说明](RELEASE_NOTES_v0.19.0.md)。标记为预发布，附件为以下三种发行物及各自的 `.sha256` 文件：

| 文件 | 用途 |
| --- | --- |
| `ZAOWU-0.19.0-windows-x64-setup.exe` | 图形安装候选，自带 Python 与界面 |
| `ZAOWU-0.19.0-windows-x64.zip` | 完整解压后使用的 Windows 应用 |
| `game-creation-workbench-0.19.0.zip` | 源码与预构建界面，需要 Python 基础依赖 |

安装包未签名，干净 Windows 虚拟机验证尚未完成。不显示虚构的 CI 徽章、下载量、公开下载地址或正式发行状态。附件放在 Releases，源码仓库不提交运行时和构建缓存。

本轮检查见[上传准备记录](GITHUB_READINESS_2026-10-28.md)，实际操作见[上传与发布指南](GITHUB_RELEASE.md)。
## 新品牌候选 v0.19.1

标题：`v0.19.1 — Questweft AI Indie Game Workbench`。正文见 [品牌更新说明](RELEASE_NOTES_v0.19.1.md)。上传新版 Questweft 安装器、Windows ZIP 与源码 ZIP 及各自校验文件后，再切换官网发布元数据；当前没有将未上传附件伪装为可下载地址。
