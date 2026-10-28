# v0.18.0 — Guided first run & optional tool setup

本版让第一次使用的人先体验项目管理，再按需要启用AI和创作工具。

- 新增“检查基础 → 选择与装配 → 开始创作”的中英文向导，首次空白工作台自动进入，已有用户可随时打开。
- 新增Install/Repair入口，缺少Python时提供Windows装配或官方指引；发布界面版本和哈希匹配时，核心管理跳过Node/npm。
- 支持固定来源的Node、Git、Blender和独立Codex装配清单；Suno Skill、API、WebUI与引擎提供对应指引。系统确认、软件许可和账号授权由本人完成。
- 新增不调用AI的幂等练习项目，包含总纲、入门文档和待执行任务。工具安装不加入Agent目录，不改变整机、全功能或积分授权。
- 装配失败停止后续依赖；中断与超时标记待核对，不自动重放安装。原Python轻量启动及数据保护保持。

验证：202项Python测试、语言检查和生产构建通过；Windows原生PowerShell模拟缺少Python/Node与损坏界面，隔离浏览器验证向导、模拟装配和免费练习流程。本轮没有在用户电脑实际安装/升级软件，也没有真实模型、收费生成或引擎运行验收。构建仍有较大分块提示。

ZIP含源码、预构建界面及哈希清单，仍需Python后端依赖；尚无私有运行时、签名安装器或自动升级回退。首次步骤、装配范围和后续易用性计划见[首次指南](QUICK_START_AND_SETUP.md)。

[中文首页](../README.md) · [English](../README_EN.md) · [使用手册](USER_GUIDE.md) · [安全与数据边界](../SECURITY.md)
