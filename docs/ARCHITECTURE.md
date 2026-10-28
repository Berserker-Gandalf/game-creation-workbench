# 架构与接口

完整的调用流程、上下文规则、资产与数据模型参见 [技术架构与开发接口说明](TECHNICAL_OVERVIEW.md)；本文件保留架构摘要与历史演进。

```text
浏览器中的 React 工作区
          │ 本机 HTTP / 流式对话
FastAPI ──┼── SQLite：项目、文档版本、任务依赖、资产版本、消息、执行记录
          ├── 本地文件：导入素材、编辑版本、备份
          ├── 官方 Codex App Server：会员登录、模型、工程工具
          │       └── 每轮专用 MCP 桥：单项目，讨论/执行范围
          ├── OpenAI / DeepSeek：Responses 流、函数工具
          ├── OpenAI Images：生成、参考图/遮罩编辑
          ├── Suno.cn 原版 Skill helper：网页授权、用户确认的音乐任务
          └── 引擎回环 HTTP：Unreal Python / Unity Editor C#
```

`backend/store.py` 管理 SQLite；新增任务表使用 `CREATE TABLE IF NOT EXISTS` 保留 0.1 数据。`tasks.py` 校验依赖无环、同项目引用、设计版本及复核；`image_jobs.py` 每次动作只提交一次付费请求，保护原资产，迟到的冲突结果保存为独立候选。

`app.py` 提供 API 和生产前端静态文件；`agent_tools.py` 是工作台工具权限入口，`codex.py` 管理官方子进程，`mcp_bridge.py` 只转发当前项目的短期令牌请求。接口文档在本机 `/docs`。密钥不返回给浏览器或模型工具。

任务进度只来自数据库记录。设计版本变化会保留已完成任务的历史状态和依据，单独标记复核并从当前已验收数量排除；关联依赖未完成或需复核时不能进入进行中、待验收或完成。设计复核需创作者明确采用当前文档版本并重新安排。这里不进行语义级代码影响推断。

备份格式 2 增加 `task_dependencies`、`task_documents`、`task_reviews`；恢复时重建项目和实体 ID，保留原采用的文档版本。格式 1 仍可导入。备份不是完整游戏工程打包器。

当前大项目上下文有容量上限，超限会明确停止，不静默截断正式规则；未实现向量检索。图像请求最多提交一张、输出固定 1024×1024，模型 ID 由用户指定。没有金额预算或供应商账单核对，usage 不是价格估算。

## 官方接口依据

开发时核对日期：2026-10-25。供应商接口和账号权限可能变化，模拟测试只验证本项目行为。

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)：官方本机运行时。
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)：项目工具连接。
- [OpenAI Responses 函数调用](https://developers.openai.com/api/docs/guides/function-calling)：工具调用循环。
- [OpenAI Image Edit](https://developers.openai.com/api/reference/resources/images/methods/edit)：本项目采用 JSON `images[].image_url` 与可选 `mask.image_url`，发送 PNG data URL，保存返回的 `b64_json`。
- [OpenAI 图像指南](https://developers.openai.com/api/docs/guides/image-generation)：透明遮罩只提供编辑指导，不承诺精确边界。
- [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/)：使用其官方兼容入口；具体模型/图像输入支持需真实验证。
- [SUNO 官方平台](https://platform.suno.com/)：当前仅链接与手动导入，未配置非官方生成接口。

## 后续开发顺序

1. 有效 API Key 下完成两家文本对话与图片生成/编辑验收，保存脱敏记录。
2. Unity 激活后完成桥接、材质修改、预览和关闭重开验收。
3. 提供受限窗口的本机操作、暂停和恢复；确定可验证范围后再开放工具。
4. 引入供应商任务 ID、长任务恢复和预算预留，再考虑 SUNO 的正式接入。
5. 按真实项目规模增加资料检索和内容验收。多用户产品需要独立认证与隔离设计。

0.3 新增 `music.py` 与 `music_jobs` 表；备份格式 3 增加音乐记录，兼容格式 1/2。音乐角色独立保存对话，所有收费提交通过用户确认界面，不在模型工具中暴露。参见 [音乐 Skill](SUNO_CN_SKILL.md)。

## 0.4 会话和执行证据

`conversations.py` 管理工作台持久会话；`chat.py` 负责每轮上下文、请求和取消。`messages`/`runs` 增加会话及模型关联，`tool_events` 记录调用摘要，`model_checks` 按服务/模型/能力记录验证。旧数据库仅增加列和表，不清空数据。备份格式 4 保留这些关联，兼容格式 1–3。

每轮 Codex 临时线程先关闭继承工具，再读取实际 MCP 目录进行白名单核验；没有原生线程续接。近期历史最多约 60000 字符，超出条数明确写入上下文，提供 `read_history` 检索；文档超过 4000 字符显示索引与片段，通过 `read_document` 分段读取完整内容。目录超过总容量时明确停止。

浏览器本地存储按项目/会话/文档保存未提交草稿。项目 ZIP 仅备份已提交数据库内容。当前仍是单用户串行角色执行，工具日志用于追溯，不提供自动重放收费操作。
