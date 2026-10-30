# 参与开发

本项目目前是本地单用户实验版，优先修复可复现的问题、完善测试与双引擎验收。请遵循 [AGENTS.md](AGENTS.md)，保持修改范围明确。

## 开发环境

建议 Python 3.12 和 Node.js 24。Windows开发执行 `scripts/Setup.ps1 -InstallMissing -RebuildUI`；其他系统按 README 的手动步骤安装。依赖使用 `requirements.lock.txt` 和 `package-lock.json` 固定版本。

先构建一次前端，然后分别运行两个终端：

```text
python -X utf8 -m backend.run
npm run dev
```

前端开发地址为 `http://127.0.0.1:5173`，API 转发到 `8765`。从仓库根目录运行后端；开发数据仍保存在 `.workbench/`。

## 验证

```text
python -X utf8 -m pytest -q
npm run build
python -X utf8 scripts/check_release.py
```

最后一项使用 Git 已跟踪/已暂存的文件清单。新增源码先加入暂存区，否则不会进入检查或发布包。它只检查常见泄漏模式，不能替代人工审阅。

默认测试不调用真实模型、引擎或付费服务。新增外部接口应使用模拟响应覆盖成功、失败、提前断流和权限拒绝。真实验收脚本需明确说明用量和修改范围，使用独立工程；不要让 CI 读取开发者的账号凭据。

提交 PR 时说明问题、最终行为、验证结果和未验证边界。引擎修改必须说明编辑器版本，保存成功与关闭重开后的结果分别记录。测试通过不等于游戏可玩。

## 发布

版本号同步修改 `package.json`、`package-lock.json`、`backend/__init__.py`、界面版本与 CHANGELOG。构建后运行 `python scripts/package_release.py` 生成 `.releases/` 下的源码和界面压缩包。压缩包不含 Python/Node 运行时，也不是独立安装器。

Windows 主机另运行 `python scripts/package_windows.py`，生成自带 Python 的应用 ZIP、图形安装候选及校验文件。运行时、编译产物和包仅作为 Releases 附件，源码仓库不提交 `.runtime/`、根目录应用 EXE 或打包标记。v0.19 安装候选未签名，源码 CI 不等于干净机器安装验收。

GitHub 发布步骤与审阅清单见 [docs/GITHUB_RELEASE.md](docs/GITHUB_RELEASE.md)。
