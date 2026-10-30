# 游织工坊 Questweft：品牌与搜索说明

日期：2026-10-29。当前源码版本：v0.19.1；当前已公开的下载附件仍为旧品牌 ZAOWU v0.19.0，须在新附件发布后更新下载信息。

## 名称与标志

中文名称：**游织工坊**。英文名称：**Questweft**。标准描述：**AI 独立游戏制作工作台**。

“游织”表示把设计、代码、美术、音乐与模型织成一个游戏。Questweft 组合探索（quest）与纬线（weft）的含义，以可识别的品牌词配合明确的产品类别，避免仅使用宽泛的“造物”类名称。

本轮对“游织工坊”和“Questweft”进行了公开网页精确词组初筛，没有获得明确的同名产品结果；搜索索引有覆盖与时效限制，不将此初筛视为商标、域名或公司名称的登记结论。可复核的检索词为 `"游织工坊"`、`"Questweft"`。

新标志为圆角交织的 Q 形图案：细化环形轮廓，以留白表现织带的穿插，保留墨绿、暖铜与纸色。它是本项目原创 SVG，不使用第三方商标或生成式素材。软件与网站共享相同图形；同时提供 favicon、手机图标、Windows ICO 和社交分享封面。

## 已同步的入口

- 软件侧栏、中文与英文窗口标题、API 元信息、目录选择与启动/安装窗口。
- 新版 `Questweft.exe`、`Questweft-Picker.exe`、Windows ZIP、安装器和开始菜单快捷方式。
- 官网静态 HTML 与双语文案、功能截图、图标、分享封面、Open Graph/Twitter、软件结构化数据。
- 双语 README、当前使用与技术指南、GitHub About/Topics 建议及发布操作说明。

仓库继续使用 `Berserker-Gandalf/game-creation-workbench`，网站继续使用既有 Pages 地址，不要求仓库迁移或购买域名。

## 有意保留的旧标识

| 标识 | 保留原因 |
| --- | --- |
| `%LOCALAPPDATA%/ZAOWU/data` | 兼容已安装版本的数据库、项目、工具与授权记录，不因改名迁移或清空。源码仍使用 `.workbench/`，`WORKBENCH_DATA` 仍有效。 |
| `game-workbench`、`WORKBENCH_*`、实例/会话标识 | 保持本机协议、启动归属校验、配置和已有集成兼容。 |
| `zaowu-site-language`、`zaowu-site-motion` | 延续浏览器已保存的语言与动效选择。 |
| `ZAOWU-Picker.exe` 回退 | 优先使用新名称的助手，同时允许旧版文件布局继续工作。 |
| v0.19.0 的 ZAOWU 附件名、校验链接和发布元数据 | 这些是已公开的真实文件，不能只改链接名称。官网会注明是旧品牌下载；解析器同时支持新旧两类文件名。 |
| 原有版本日志、验证 JSON、历史截图、案例视频/配音/封面 | 保留原始事实和哈希；历史记录中的品牌不是当前展示入口。官网展示改用新品牌截图，案例媒体仍不进入网站。 |
| 原 LICENSE 的贡献者署名 | 更名不改写既有版权归属。 |

新版程序安装在独立的 Questweft 版本目录，数据继续复用旧目录。升级前应正常停止旧程序，按原流程备份后再打开新版；不自动删除旧程序，不扩大 Agent 权限。

## 搜索内容设计

中文页面标题为“游织工坊 Questweft｜AI 独立游戏制作与项目管理工作台”，英文界面标题为“Questweft — AI Indie Game Development Workbench”。主标题和可见介绍自然覆盖以下主题：

`AI 独立游戏制作`、`AI 游戏开发`、`Unity / Unreal`、`AI 游戏设计`、`AI 美术`、`游戏音乐`、`3D 建模`、`游戏资产管理`。

这些词写入静态页面标题、可见正文和描述，同时保持品牌、README 和分享信息一致；不靠隐藏文字或重复堆砌关键词。页面增加 `SoftwareApplication` JSON-LD 和 `sitemap.xml`，只描述已有功能，不添加虚构评分、下载量或已发布的新附件。

依据：[Google 标题建议](https://developers.google.com/search/docs/appearance/title-link)、[摘要与描述建议](https://developers.google.com/search/docs/appearance/snippet)、[站点地图说明](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview)、[SoftwareApplication 类型](https://schema.org/SoftwareApplication)。

当前 Pages 是仓库子路径，Google 的独立“站点名称”标记不支持子目录，所以没有把 `WebSite` 标记当作独立站点名保证。页面仍可通过标题、内容和链接被索引。参见 [Google 站点名称限制](https://developers.google.com/search/docs/appearance/site-names)。

## 上线后的操作

1. 上传新源码与网站文件，等待 Pages 成功部署。网站更新不等于新版软件附件已发布。
2. GitHub About 使用下方短介绍，并按 [主页介绍](GITHUB_HOME_PAGE.md) 设置 Topics 与 Website。
3. 发布 v0.19.1 的三类附件及各自校验文件，确认下载实际可用后，再更新 `docs/site/release.json` 的版本、附件名、URL、大小与 `appName: "Questweft"`。不要覆盖或重命名 v0.19.0 的旧附件。
4. 可通过站长平台验证网站所有权，提交正式首页和站点地图地址。未在本轮登录或代提交站长账号。

建议 About：

> 游织工坊 Questweft：开源、本地运行的 AI 独立游戏制作工作台。连接 Unity / Unreal、AI 设计、美术、音乐与 3D 建模，管理任务、资产版本和项目快照。

关键词与地图帮助搜索引擎理解和发现内容，不保证收录时间或排名。外部搜索结果、社交缓存与线上名称只有在实际上传并重新抓取后才会变化。

本轮验证见 [brand-v0.19.1.json](verification/brand-v0.19.1.json)：包含 12 张新品牌双语截图、图像哈希、14 组屏幕检查与测试边界。此前日期的验证记录继续描述对应历史版本。
