# 官网设计与素材规范

## 本轮范围

优化 `docs/index.html` 的静态介绍与下载体验。网站继续通过 GitHub Pages 的 `main /docs` 发布，工作台继续在本机运行。根据用户要求，官网不展示或托管案例视频；案例媒体统一移到仓库根目录 `media/case-study/`，不存在官网播放器页面。

## 设计依据

本轮安装并实际使用两项技能：

- [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/28b3b8dee8c976df4fa3e94aed4e092ad43fcb03/.claude/skills/ui-ux-pro-max)：原作者版本 `28b3b8d`，使用本地设计检索与触控、键盘焦点建议。首次检索返回文档站，不适合本产品；缩小为 `design tool landing` 后匹配产品展示结构。最终采用真实截图与功能说明，用户的无视频要求优先。
- [Web Asset Generator](https://github.com/alonw0/web-asset-generator/tree/c6d56dc54ab86eae4eeb1393d9c8cdc71ae8d1a8/skills/web-asset-generator)：原作者版本 `c6d56dc`，实际运行 favicon、手机图标和 Open Graph 图片生成及校验脚本。现有原创 SVG 为图标源，分享卡使用品牌文字和真实示例截图，不调用付费图像服务。

技能安装在个人 Codex 技能目录，不复制到产品运行依赖中。两者为 MIT 许可；生成素材继续沿用项目品牌。图片、尺寸和标签需要一起维护。

## 页面结构

1. 首屏：一句话定位、明确的 Windows 下载按钮、使用指南和真实界面。
2. 可选创作工具：文字列举，避免误导为全部已经连接或得到官方背书。
3. 四项能力：两列展示，手机改为单列，保留足够正文空间。
4. 三步上手：浅色区分段，说明安装、项目接入和交付留存。
5. 软件截图：支持中英文切换、硬件预检、大图预览和键盘退出。
6. 下载与问题：推荐安装包、免安装包、源码及各自的校验文件；异常发布信息保留真实 Releases 入口。

## 视觉与交互

- v0.19.1 使用原创圆角交织 Q 形标志，保留墨绿背景 `#142023`、暖铜强调 `#e8b18b` 和纸色 `#eee8dd`。不套用检索结果中的默认青绿色，也不引入新的字体下载依赖。
- 正文基准 16 px，主要说明采用 15–17 px，行高约 1.7–1.85；装饰性标签与辅助文字单独缩小。
- 项目目标为主要按钮、导航和切换控件至少 44 px 高；这是一项易用性选择，不将其声称为所有平台通用的法规阈值。
- 焦点环、原生折叠问题、原生截图对话框和减少动态效果样式继续保留。系统减少动态效果的设置不会被网站改动。
- 没有自动播放、轮播、跟踪脚本、第三方字体请求或公开工作台 API。
- 已计算的主要正文与按钮配色对比度均高于 4.5:1；这不是完整无障碍认证。

## 生成素材

`docs/site/icons/`：16/32/96 px favicon、含 16/32/48 px 图层的 ICO、180 px Apple 图标及 192/512 px 通用手机图标。生成这些图标不代表网站已经具备离线 PWA 功能。

`docs/site/social/og-image.png` 为 1200×630，`twitter-image.png` 为 1200×675。页面使用正式 Pages 地址的绝对 HTTPS 图片 URL；favicon 使用项目内相对路径，以兼容仓库子路径。

社交平台的实际抓取效果须在上传、Pages 部署完成后核对；本机尺寸与格式检查不能证明外部平台已经刷新缓存。

## 验证入口

`node --test tests/website.test.mjs tests/beacon-route.test.mjs` 检查双语文案、页面锚点、资源路径、发布附件、图标与分享图尺寸，以及案例视频不进入 Pages 目录的边界。前端构建、Python 测试与公开文件检查沿用仓库要求。

本轮的实际验证范围见 [website-redesign-v0.19.json](verification/website-redesign-v0.19.json)。

后续审查修复了窄屏页头与锚点、横屏阅读空间、发布信息超时和截图原图查看；具体发现、验证及剩余边界见 [官网审查记录](WEBSITE_REVIEW.md) 与 [website-audit-v0.19.json](verification/website-audit-v0.19.json)。原始设计验证记录保留，不覆盖历史结果。

动态交互版本增加了首屏四页缩略图、完整六页功能展示、滚动与鼠标反馈，并提供遵循系统偏好的动效开关。当前交互、截图来源及验证范围见 [动态交互说明](WEBSITE_MOTION.md)；原始“没有轮播”约束继续保留，图库采用手动切换。
