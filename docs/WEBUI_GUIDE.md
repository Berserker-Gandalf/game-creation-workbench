# 本机 Stable Diffusion WebUI 接入与创作管理

> 0.19 更新：已提供自带 Python 的 Windows x64 安装候选、系统目录/文件选择、原版 SUNO Skill 装配和只读 WebUI 硬件预检。详细步骤与验证边界见[应用与装配指南](WINDOWS_APP_AND_SETUP.md)；下文旧版本验收记录保留其当时范围。

适用版本：0.5.0。本版面向 A1111 兼容 WebUI，提供本机连接、Checkpoint / LoRA 目录、生成参数、图生图、产出浏览和项目导入。

## 使用方式

1. 在 **WebUI 绘画 → 本机连接** 填写安装根目录与 API 地址，点击 **保存连接**。目录应包含 `modules/api/api.py` 和 `models`。
2. 从原来的绘世/WebUI 启动器启动服务，在启动参数中启用 `--api`，并显式使用 `--server-name 127.0.0.1`。保持只在本机访问，不需要 `--listen`。
3. 常用地址为 `http://127.0.0.1:7860`；若原启动器使用其他端口，在工作台同步填写。安装目录和地址分别保存，不会自动寻找所有本机进程。
4. 点击 **检查连接 / 扫描本地**。离线仍可浏览文件目录；只有实际 API 可选的模型和 LoRA 才可用于生成。
5. 在 **主模型** 或 **LoRA** 中搜索资源，加入默认选择；在 **默认生成参数** 调整参数并保存。
6. 选择一个项目，点击 **保存并前往美术创作**。资产区的 **绘画来源** 可以切换 OpenAI 与本机 WebUI。

工作台不自动安装、升级、启动或停止用户的 WebUI，也不下载、移动或删除模型文件。通过原启动器运行可以保留整合包原有的 Python、缓存和运行设置。

## 模型与 LoRA 管理

- 默认扫描安装目录内 `models/Stable-diffusion` 与 `models/Lora`，支持常见 safetensors / ckpt / pt 文件登记；读取文件信息不等于加载或验证了该模型。
- 页面显示名称、相对路径、大小、可读取的基底信息与别名。safetensors 仅有限读取 JSON 头，不反序列化模型权重，不使用 pickle 读取 ckpt。
- 在线目录与本地文件匹配后才标记 **API 可选**。模型名称和 API 标题可能不同，以实际映射为准。
- 一次最多选择 8 个 LoRA，权重范围 -2 到 2。工作台根据 API 名称生成 `<lora:名称:权重>`，不开放手写额外网络标记。
- 基底兼容性需要人工判断。例如 SD1.5、SDXL、Flux 的 LoRA 不能仅因出现在同一列表就混用。必要触发词请在正面提示词中自行填写；本版不自动推断。
- **刷新 WebUI 模型索引** 只请求 WebUI 重新建立模型和 LoRA 目录，不下载、删除或改名文件。
- 默认参数保存在工作台设置中；不写入 WebUI 的 `config.json`。生成通过单次 `override_settings` 选择主模型，要求生成后恢复原设置。

离线目录单类最多扫描 2000 项。本版尚未支持外部自定义模型目录、任意远程服务器、WebUI API Basic Auth 配置、模型下载/删除或训练功能。

## 文生图与图生图

**文生图：**在资产区填写正面提示词，选择 WebUI 来源、模型、LoRA 和采样参数，再点击生成。

当前开放宽高 64–2048（8 的倍数）、步数 1–100、CFG 1–30、Seed（-1 随机）及负面提示词；一次一张，不自动开启高清修复或附加脚本参数。

**图生图：**打开项目图片详情，在 AI 图片编辑中选择 WebUI，填写需求和重绘幅度。输入必须为本项目的有效图片，并使用当前版本哈希。

**局部重绘：**选择同尺寸、带完全透明区域的 PNG 遮罩。界面保持“透明部分表示修改区域”的约定，后端会将其转换为 WebUI 使用的白色重绘区域。遮罩不保证结果边界完全准确，仍需人工验收。

生成结果保存为项目资产或图片新版本。若原图在生成期间发生变化，结果另存为独立候选，避免覆盖新版本。新图和编辑图均保留创作记录。

本机生成会占用显存和 GPU。工作台一次只提交一个 WebUI 请求，不会自动重试；它不能协调原生 WebUI 页面或其他程序发起的所有请求。当前没有面向共享 WebUI 的全局停止按钮。

## 产出与项目记录

### WebUI 原有产出

在 **WebUI 产出** 中按文件名搜索，查看原图，或导入当前项目。默认识别安装目录中的 outputs、log/images，以及 config.json 中位于安装目录内部的输出目录；外部输出路径和符号链接越界不开放。

导入是复制到工作台项目，不移动原文件。同项目重复导入同一文件版本会复用已有资产；文件变化后必须刷新列表。PNG 中的 parameters 信息会保留，并进入导入记录。

产出列表按已扫描文件的修改时间排序，支持翻页；大目录达到扫描上限时会提示，不应把当前列表理解为无限文件索引。

### 工作台创作记录

在 **项目创作记录** 中查看最近 100 条生成或导入记录，也可在资产详情查看 **创作参数与来源**。

记录包括来源、状态、所选模型、LoRA 与权重、提示词、采样参数、实际 Seed（若返回）及生成信息。失败请求也保留记录，不会伪造图片或标记为成功。

记录用于追溯，不提供自动重放、自动验收或精确质量评价。原生 WebUI 产出的 PNG 信息可能不完整，工作台不会据此推断不存在的 LoRA 或种子数据。

## 开发接口

| 接口 | 用途 |
| --- | --- |
| `GET/PUT /api/webui/config` | 读取/保存本机目录、地址和工作台默认参数 |
| `GET /api/webui/catalog?live=false` | 只扫描离线模型/LoRA |
| `GET /api/webui/catalog` | 本地目录与 API 目录合并，返回在线状态、当前模型、采样器 |
| `POST /api/webui/refresh` | 请求 API 刷新模型/LoRA 索引 |
| `GET /api/webui/outputs` | 产出列表，query / offset / limit |
| `GET /api/webui/output-file` | 按相对 path 读取产出；thumbnail=true 返回缩略图 |
| `POST /api/projects/{pid}/webui/import` | path + version 导入当前项目 |
| `GET /api/projects/{pid}/art-jobs` | 最近项目创作记录 |

原生成接口继续使用，新增 `provider=webui`；省略 provider 时保留 OpenAI 行为。

```json
{
  "provider": "webui",
  "prompt": "small room, pixel art, warm light",
  "checkpoint": "models/Stable-diffusion/example.safetensors",
  "sampler": "Euler a",
  "width": 512,
  "height": 512,
  "steps": 20,
  "cfg_scale": 7,
  "seed": -1,
  "negative_prompt": "",
  "loras": [
    {"id": "models/Lora/example-style.safetensors", "weight": 0.8}
  ]
}
```

checkpoint 和 LoRA ID 必须使用当前目录返回的真实值。图生图仍走 `/api/assets/{aid}/ai-edit`，另传 `expected_hash`、可选 `mask_asset_id` 和 `denoising_strength`。

后端固定组装允许的请求字段，不把任意 override、脚本、外部 URL 或模型下载参数直接转交 WebUI。连接仅允许回环 HTTP 根地址，不跟随重定向。若原 WebUI 已设置认证，本版会提示不支持该连接配置，不会自动关闭认证。

`art_jobs` 保存参数与结果摘要，图片内容仍由 assets 版本机制管理。备份格式 5 增加创作记录，恢复时重映射 run/asset 及结构化参考图关联；不包含模型、LoRA、WebUI 全局设置和运行环境。兼容导入格式 1–4。

## 本次验收

已在独立数据区读取本机 2 个主模型、6 个 LoRA 和 177 个原有产出；真实文生图、图生图、LoRA 组合、Seed/PNG 参数记录、图片版本保存及原有产出导入通过。生成测试为 256×256、2 步，不是美术质量验收。全部 49 项自动测试与生产构建通过。脱敏证据见 [WebUI 验证记录](verification/webui-v0.5.json)。

首次独立启动未沿用绘世缓存环境而发生 HTTPS 获取错误；失败已记录。随后复用已有 tokenizer 缓存、使用独立离线缓存和配置完成验证，没有关闭 TLS 校验或修改原安装脚本/设置。

## 故障处理

| 情况 | 处理方式 |
| --- | --- |
| 能扫描模型但 API 离线 | 从原启动器启动并启用 --api，核对端口，再检查连接 |
| API 连通但 LoRA 仍仅离线可见 | 核对内置 LoRA 扩展及对应 API；不要把“主 API 在线”等同于每个扩展可用 |
| 模型/LoRA 不可选 | 检查 API 是否识别该文件，以及是否位于本版支持的目录内 |
| 生成 HTTP 500 | 先看原 WebUI 日志，核对模型、基底、VAE、显存和缓存；不直接重复提交 |
| CLIP/Hugging Face 获取失败 | 优先从绘世启动器运行，核对其现有 HF/Transformers 缓存环境；不要禁用 HTTPS 校验解决问题 |
| 生成超时 | 原 WebUI 可能仍在运行，先核对原生页面与输出目录 |
| 原有图片不在产出列表 | 检查是否为自定义外部目录、超出扫描上限或不支持的图片后缀 |
| 导入提示版本变化 | 刷新产出列表后重新选择；不要强行覆盖项目资产 |
| 备份恢复后没有模型 | 模型与 LoRA 不属于项目资产备份，需要在目标电脑单独配置 |

接口依据：[A1111 API 说明](https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API)。该 wiki 自身提示部分说明较旧，因此实现同时核对了本机安装源码；实际兼容性以当前 WebUI `/docs` 和可复现验证为准。
