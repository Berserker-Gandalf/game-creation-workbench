# 介绍与下载网站

网站源文件位于 `docs/index.html` 与 `docs/site/`。v0.19.1 的功能截图位于 `docs/site/screens/`；原有 `docs/verification/` 保留历史证据。它是独立静态介绍页，不连接工作台的本机 API，不承载用户项目，不需要服务器运行 Python。

## 页面内容与本地预览

页面提供软件介绍、创作流程、界面截图、中英文切换、常见问题和三类下载入口。语言偏好仅保存在访客浏览器。页面不安装第三方字体或统计脚本；发布信息从同源 `site/release.json` 读取，访客不需要 GitHub Token。

从仓库根目录运行：

```text
python -m http.server 8780 --bind 127.0.0.1 --directory docs
```

打开 `http://127.0.0.1:8780/`。不要直接双击 HTML 预览下载状态，浏览器可能限制本地文件读取 JSON。

网站专项检查：

```text
node --test tests/website.test.mjs
```

该检查覆盖真实附件格式、预览版与未发布状态、缺少附件、校验文件配对、非预期 URL、项目子路径、页面锚点、图片资源和双语文案。原 `Verify workbench` 增加此步骤。

## 发布到 GitHub Pages

1. 将新增的网站文件与更新后的 CI、测试和本指南提交到仓库。保留原有 `docs/verification/` 截图目录。`docs/.nojekyll` 是静态发布标记；如果网页上传提示隐藏文件，可用 **Create new file** 按此完整路径在线创建，正文保持本机文件内容。
2. 进入仓库 **Settings → Pages**。
3. 在 **Build and deployment → Source** 选择 **Deploy from a branch**。
4. Branch 选择完整源码所在的 `main`，Folder 选择 **/docs**，然后 Save。
5. 等待 Pages 的构建/部署工作流通过。以 Settings → Pages 返回的实际站点地址为准；正常项目地址形式为 `https://berserker-gandalf.github.io/game-creation-workbench/`。配置前不要把该地址称为已上线。
6. 打开已部署站点，检查语言切换、截图预览、下载和文档链接。在仓库首页 About 的齿轮中，将 Website 改成实际 Pages 地址。

Pages 只发布 `/docs` 静态文件。本机工作台继续按原方式运行；不要将仓库根目录的开发界面直接当作线上工作台发布。

使用网页上传时，解压网站上传包，进入 `repository-files`，在仓库根目录上传其中的 `docs`、`tests` 目录。不要把 ZIP 本身上传为源码，也不要多套一层 `repository-files`。`.github/workflows/ci.yml` 可在 GitHub 原文件页面点击编辑，用包内对应内容更新；此步骤只是加入网站自动检查，Pages 页面本身无需这个工作流。隐藏的 `docs/.nojekyll` 用 **Add file → Create new file** 创建，文件名填完整路径，内容填写：

```text
Static product site. Serve files directly without Jekyll processing.
```

上传后应能在仓库中直接打开 `docs/index.html`、`docs/site/main.js`、`docs/site/style.css`、`docs/site/release.json`、`docs/site/mark.svg`、`tests/website.test.mjs`。不要替换已发布的 v0.19.0 软件附件；网站文件单独提交即可。若本机仓库与网页上传的历史不同，不要强制推送覆盖远端。

依据：[GitHub Pages 发布源配置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 下载链接与版本更新

`docs/site/release.json` 是公开发布信息的快照。本版的 v0.19.0 与六个附件在 2026-10-28 经仓库 Releases API 核对，包含预览版安装包、Windows ZIP、源码 ZIP 及对应校验文件。页面显示该明确版本，不依赖只指向正式版的 `releases/latest`。

发布新版本后，再从实际 Release 复制版本、附件名称、大小和下载 URL，更新 JSON。只填已公开的附件；`published` 只有在公开后才设为 `true`。不要根据未发布的标签猜测下载地址。每个附件 URL 必须属于本仓库对应版本，校验文件名称为附件名加 `.sha256`。

缺少某个附件时，该卡片回到版本发布页；发布信息未确认或读取失败时，保留 GitHub Releases 入口并明确状态。页面不自动下载或执行安装包。

## 是否需要 GitHub Packages

| GitHub 功能 | 当前用途 |
| --- | --- |
| Repository | 工作台与网站源码、手册、问题反馈 |
| Releases | 安装包、Windows ZIP、源码发行包及校验文件 |
| Pages | 软件介绍与下载导航网站 |
| Packages | 当前不需要；以后分发 npm 库、NuGet 包或容器镜像时再考虑 |

`package.json` 是本项目的前端依赖清单，与是否开通 GitHub Packages 是两回事。现在保持其 `private: true`；不为建立下载网站而发布 npm 包或 Docker 镜像。

依据：[GitHub Packages 介绍](https://docs.github.com/en/packages/learn-github-packages/introduction-to-github-packages)。
