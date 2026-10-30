import { setupMotion } from './motion.js';

export const REPO = 'https://github.com/Berserker-Gandalf/game-creation-workbench';
export const RELEASES = REPO + '/releases';
export const COPY = {
  heroCategory:['AI 独立游戏制作工作台','AI INDIE GAME WORKBENCH'],
  legacyDownloads:['公开下载目前仍为更名前的 v0.19.0（ZAOWU）；游织工坊 Questweft v0.19.1 将在新版附件发布后提供。','Public downloads still use the previous ZAOWU name at v0.19.0. Questweft v0.19.1 will be available after its new release assets are published.'],
  portableLegacyBody:['此公开附件仍使用旧品牌：完整解压后打开 ZAOWU.exe。项目与数据目录保持兼容。','This published asset uses the previous name. Extract it fully and open ZAOWU.exe. Project and data directories remain compatible.'],
  integrationsLabel:['可选工具与服务','Optional tools and services'],
  navigationLabel:['网站导航','Site navigation'],screenshotsLabel:['界面截图','Screenshots'],dialogLabel:['截图预览','Screenshot preview'],switchLanguage:['切换为英语','Switch to Simplified Chinese'],openOriginal:['打开原图 ↗','Open original image ↗'],sharingAlt:['游织工坊 Questweft · 本地游戏创作与项目管理工作台','Questweft · A local workspace for game creation and project management'],
  heroScreensLabel:['探索工作台功能','Explore workbench features'],viewDesign:['设计资料','Design library'],viewTasks:['任务看板','Task board'],viewMusic:['音乐创作','Music studio'],viewModeling:['角色建模','Character lab'],
  designCaption:['保存设计版本与权威状态，让讨论和修改有据可循。截图为本机示例资料。','Save design revisions and authority status, keeping decisions traceable. Local sample documents shown.'],tasksCaption:['按状态查看任务，关联设计与交付物。截图为示例任务，不代表引擎验收。','Organize tasks by status and link designs to deliverables. Sample tasks shown; no engine acceptance implied.'],musicCaption:['为音乐负责人准备场景、风格与生成模型。截图展示本机方案界面，未调用收费生成。','Prepare scenes, styles and generation models with the music lead. Local planning interface shown; no paid generation called.'],modelingCaption:['配置本机 Blender 角色比例、服装与配件。截图展示方案界面，不代表自动绑定或引擎验证。','Plan local Blender proportions, outfits and accessories. Planning interface shown; no automatic rigging or engine verification implied.'],
  designAlt:['游织工坊设计资料：设计正文、版本与权威状态','Questweft design library: document content, revisions and authority'],tasksAlt:['游织工坊任务看板：示例任务、状态与验收入口','Questweft task board: sample tasks, statuses and review controls'],musicAlt:['游织工坊音乐工作区：Suno.cn 模型与音乐方案','Questweft music studio: Suno.cn model selection and music planning'],modelingAlt:['游织工坊角色建模：本机 Blender 方案与参数','Questweft character lab: local Blender planning and parameters'],
  galleryHint:['选择功能页，看看不同环节如何衔接。支持方向键切换与查看原图。','Choose a feature to explore the workflow. Use arrow keys to switch, or open the original image.'],motionOn:['动态效果：开启','Motion: on'],motionOff:['动态效果：关闭','Motion: off'],motionSystem:['动态效果：遵循系统关闭','Motion: reduced by system'],
  skip:['跳到正文','Skip to content'],brand:['游织工坊','Questweft'],navFeatures:['能做什么','Features'],navWorkflow:['如何开始','Get started'],navDownload:['下载','Download'],navQuestions:['常见问题','Questions'],
  heroLine1:['AI 独立游戏制作，','AI indie game creation.'],heroLine2:['从一个想法织起。','Weave your next world.'],heroDescription:['为独立开发者连接游戏设计、AI 美术、音乐与 3D 建模。接续 Unity / Unreal 工程，把任务、资产与项目快照放在同一个本地工作台。','Connect game design, AI art, music and 3D modeling for indie development. Continue Unity or Unreal projects with tasks, assets and snapshots in one local workspace.'],
  heroDownload:['下载 Windows 预览版','Get the Windows preview'],heroGuide:['先看使用指南','Read the user guide'],heroNote:['预览版 · Windows x64 · 简体中文 / English','Preview · Windows x64 · Chinese / English'],
  valueLocal:['项目留在本机','Local project storage'],valuePermissions:['权限由你选择','Permissions you choose'],valueSource:['MIT 开源','MIT open source'],screenLabel:['一个工作空间，保留创作的来龙去脉。','Keep the work and the reasoning together.'],screenCaption:['真实界面 · 示例项目','Real interface · Sample project'],
  integrations:['选择需要的工具，让它们围绕同一个项目工作。','Choose the tools you need. Give them one project to work around.'],featuresTitle:['不止生成资产，也把项目管起来。','Create the assets. Keep the project together.'],featuresIntro:['AI 游戏开发中的想法、讨论、产出与验收各有位置。下一次打开项目，能够接着上一次继续。','Keep AI game development ideas, conversations, outputs and reviews together. Return with the context to keep going.'],
  feature1Title:['从已有工程继续','Continue existing work'],feature1Body:['接入主工程与附加资料目录，最多 8 个来源。原位登记设计与资产，不必重新开始。','Connect the main game project and supporting folders, with up to eight sources. Index designs and assets in place.'],
  feature2Title:['让讨论保留上下文','Keep decisions in context'],feature2Body:['项目、音乐与建模负责人分别协作。会话历史、资料回查和 Markdown 留存，让决定能够接续。','Collaborate with project, music and modeling leads. Conversation history, source lookups and Markdown notes help preserve decisions.'],
  feature3Title:['让多种创作连接起来','Connect creative tools'],feature3Body:['管理绘画模型与 LoRA，准备音乐和 3D 方案。审阅产出，再把采用的版本纳入项目资产。','Manage art models and LoRAs, and prepare music and 3D plans. Review outputs, then adopt specific versions as project assets.'],
  feature4Title:['把成果留得清楚','Make delivery traceable'],feature4Body:['统一作业、任务关联、固定资产版本与验收记录。通过可校验快照和独立恢复留住进度。','Track jobs, link tasks to fixed asset versions and record acceptance. Preserve progress with verifiable snapshots and independent restore.'],
  tagModels:['模型与推理强度','Models & reasoning'],tagArt:['美术','Art'],tagMusic:['音乐','Music'],tagSnapshots:['工程快照','Project snapshots'],workflowTitle:['先用起来，再按需启用工具。','Start small. Add tools when you need them.'],workflowIntro:['没有 AI 账号，也能先使用项目、设计和任务管理。','Start managing projects, designs and tasks without an AI account.'],
  step1Title:['安装，打开工作台','Install and open'],step1Body:['Windows 安装包自带基础 Python 环境。首次向导可创建免费的本机练习项目。','The Windows app includes its core Python runtime. Create a free local practice project with the first-run guide.'],
  step2Title:['接入项目与创作工具','Connect your project'],step2Body:['从系统窗口选择目录。按需装配支持工具，并在官方页面完成本人的账号授权。','Choose folders through system dialogs. Set up optional tools and authorize your own accounts on official provider pages.'],
  step3Title:['审阅产出，记录交付','Review and deliver'],step3Body:['将采用的文件关联任务，记录验收依据，保存完整工程快照，再继续下一步。','Link adopted files to tasks, record acceptance evidence and save a complete project snapshot before moving on.'],setupGuide:['阅读完整安装与装配指南','Read the full installation guide'],
  previewTitle:['每个创作环节，都有自己的工作空间。','A workspace for every part of the process.'],viewWorkspace:['项目工作空间','Project workspace'],viewHardware:['WebUI 硬件预检','WebUI hardware check'],workspaceCaption:['会话、项目资料与进度同屏；执行权限按会话保存，修改由你决定。','Conversations, project information and progress together. Editing permission is saved per conversation and stays under your control.'],hardwareCaption:['查看内存、显卡和磁盘预算；硬件建议与实际出图验证分别记录。','Check RAM, GPU information and disk budget. Hardware advice and verified image generation remain separate.'],expandImage:['查看大图 ↗','View full size ↗'],closeImage:['关闭预览 ×','Close preview ×'],
  downloadTitle:['选择适合你的开始方式。','Choose your way in.'],downloadIntro:['当前为本机单用户实验版。外部服务、模型和引擎仍按各自规则授权与计费。','An experimental, local, single-user workbench. External services, models and engines retain their own licensing and billing.'],releaseLoading:['正在读取发布信息…','Reading release information…'],releaseReady:['预览版附件已发布','Preview assets published'],releaseStable:['发布附件已公开','Release assets published'],releasePartial:['部分附件待补齐，请核对发布页','Some assets are missing. Check the release page.'],releasePending:['下载附件尚未确认，请查看发布页','Download assets are not confirmed. Check the release page.'],releaseUnavailable:['暂时无法读取发布信息，请到 GitHub 核对','Release information is unavailable. Check GitHub.'],releaseHistory:['全部版本 ↗','All releases ↗'],
  recommended:['推荐 · 第一次使用','RECOMMENDED · FIRST VISIT'],installerTitle:['Windows 安装包','Windows installer'],installerBody:['图形安装，自带 Python 和完整界面。安装后从开始菜单打开或正常停止工作台。','A graphical setup with Python and the full interface included. Start and stop the workbench from the Start menu.'],portableKicker:['完整解压后使用','EXTRACT THE COMPLETE APP'],portableTitle:['Windows 免安装包','Windows portable ZIP'],portableBody:['保留完整目录，打开 Questweft.exe 即可。程序可以另放位置，默认用户数据独立保存。','Keep the complete folder and open Questweft.exe. Place the app where you like; default user data is stored separately.'],sourceKicker:['面向开发者','FOR DEVELOPERS'],sourceTitle:['源码与预构建界面','Source & prebuilt UI'],sourceBody:['查看实现、修改工作台或参与开发。此包不含 Python，需要准备锁定的基础依赖。','Inspect the implementation, modify the workbench or contribute. Python is not bundled; install the locked core dependencies.'],
  getInstaller:['下载安装包','Download installer'],getPortable:['下载免安装 ZIP','Download portable ZIP'],getSource:['下载源码 ZIP','Download source ZIP'],openRelease:['前往发布页','View release assets'],checksum:['SHA-256 校验文件 ↗','SHA-256 checksum ↗'],checksumFallback:['在发布页查看校验文件 ↗','Find checksums on the release page ↗'],downloadNote:['预览版安装包尚未签名。干净系统、部分真实 API、收费生成和引擎运行仍需独立验收；下载文件不包含模型权重或第三方游戏工程。','The preview installer is unsigned. Clean-system operation, some live APIs, paid generation and engine runtime need separate acceptance. Downloads do not include model weights or third-party game projects.'],
  questionsTitle:['把开始前的问题，先说清楚。','A few things before you start.'],questionsIntro:['更多操作与技术细节，都在仓库手册里。','The repository guides cover setup, workflows and technical details.'],feedback:['反馈问题','Report an issue'],
  faq1Q:['需要先安装 Python 或 Node 吗？','Do I need to install Python or Node first?'],faq1A:['Windows 应用附件自带基础 Python 环境，核心项目管理无需另装 Python 或 Node。可选工具按需装配；源码开发环境按手册准备。','Windows app downloads include the core Python runtime. Core management needs no separate Python or Node installation. Set up optional tools as needed; source development follows the guide.'],
  faq2Q:['已经做了一部分的游戏可以接入吗？','Can I bring a game already in development?'],faq2A:['可以选择主工程与附加资料目录，合计最多 8 个来源。接入先扫描预览，原资产留在原处；选择目录不会自动运行工程。','Connect the main project and supporting folders, up to eight sources in total. Review the scan before import. Original assets stay in place, and choosing a folder does not run the project.'],
  faq3Q:['是否需要连接全部 AI 服务？','Do I need every AI service?'],faq3A:['不需要。可以先管理设计、任务与本地资产，再选择需要的服务。云端创作按供应商规则计费，自动积分消费需要单独授权。','No. Start with designs, tasks and local assets, then add the services you need. Cloud creation follows provider pricing. Automatic credit spending requires a separate grant.'],
  faq4Q:['能在这个网站里直接创作游戏吗？','Can I create a game on this website?'],faq4A:['本站提供介绍、文档和软件下载。工作台在你的电脑上运行，项目由本机管理；外部模型或创作服务按你选择的接口连接。','This site introduces the software and links to downloads and documentation. Run the workbench on your computer; connect external models and creative services through the interfaces you choose.'],
  faq5Q:['软件与模型的许可如何区分？','How are software and model licenses handled?'],faq5A:['工作台源码采用 MIT 许可。Python、依赖、模型、引擎、服务和用户资产保留各自许可；本项目不是这些供应商的官方产品。','Workbench source code is MIT licensed. Python, dependencies, models, engines, services and user assets retain their own terms. Questweft is not an official product of these providers.'],footerNote:['为创作留出空间，也为每一步留下依据。','Room to create. A record of how you got there.'],
  workspaceAlt:['游织工坊示例项目：项目总览、AI 会话与任务进度','Questweft sample project: overview, AI conversation and task progress'],hardwareAlt:['游织工坊 WebUI 硬件预检示例：内存、显卡、显存与磁盘建议','Questweft WebUI hardware check: RAM, GPU, VRAM and disk guidance'],title:['游织工坊 Questweft｜AI 独立游戏制作与项目管理工作台','Questweft — AI Indie Game Development Workbench'],description:['游织工坊 Questweft 是开源、本地运行的 AI 独立游戏制作工作台。接续 Unity / Unreal 工程，连接 AI 游戏设计、美术、音乐和 3D 建模，管理任务、资产版本与项目快照。','Questweft is an open-source, local AI indie game development workbench. Connect Unity or Unreal projects with AI game design, art, music and 3D modeling; manage tasks, versioned assets and snapshots.']
};

export const SCREENS = {
  workspace:{title:'viewWorkspace',caption:'workspaceCaption',alt:'workspaceAlt'},
  design:{title:'viewDesign',caption:'designCaption',alt:'designAlt'},
  tasks:{title:'viewTasks',caption:'tasksCaption',alt:'tasksAlt'},
  music:{title:'viewMusic',caption:'musicCaption',alt:'musicAlt'},
  modeling:{title:'viewModeling',caption:'modelingCaption',alt:'modelingAlt'},
  hardware:{title:'viewHardware',caption:'hardwareCaption',alt:'hardwareAlt'}
};

export function resolveDownloads(manifest) {
  if (!manifest || manifest.published !== true || !/^v\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(manifest.tag) || !Array.isArray(manifest.assets)) return null;
  const version = manifest.tag.slice(1);
  const releaseUrl = RELEASES + '/tag/' + encodeURIComponent(manifest.tag);
  if (manifest.releaseUrl !== releaseUrl) return null;
  const appName = manifest.appName === undefined ? 'ZAOWU' : manifest.appName;
  if (!['ZAOWU','Questweft'].includes(appName)) return null;
  const names = {installer:`${appName}-${version}-windows-x64-setup.exe`,portable:`${appName}-${version}-windows-x64.zip`,source:`game-creation-workbench-${version}.zip`};
  const items = {};
  for (const [kind, name] of Object.entries(names)) {
    const find = filename => manifest.assets.find(a => a?.name === filename && a.url === REPO + '/releases/download/' + encodeURIComponent(manifest.tag) + '/' + encodeURIComponent(filename) && Number.isSafeInteger(a.size) && a.size > 0);
    const asset = find(name);
    if (asset) items[kind] = {...asset, checksum:find(name + '.sha256')?.url || null};
  }
  return {tag:manifest.tag,appName,prerelease:manifest.prerelease === true,releaseUrl,items};
}

export function screenshot(view, language) {
  return `site/screens/${Object.hasOwn(SCREENS,view) ? view : 'workspace'}-${language === 'en' ? 'en' : 'zh'}.png`;
}

export async function loadRelease(url, fetcher = fetch, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(url, {credentials:'omit',cache:'no-cache',signal:controller.signal});
    if (!response.ok) throw new Error('Release metadata unavailable');
    return await response.json();
  } finally { clearTimeout(timeout); }
}

function start() {
  let language = 'zh', view = 'workspace', heroView = 'workspace', manifest = null, releaseFailed = false, releaseLoading = true;
  try { language = localStorage.getItem('zaowu-site-language') === 'en' ? 'en' : 'zh'; } catch {}
  const text = key => COPY[key]?.[language === 'en' ? 1 : 0] || key;
  const dialog = document.querySelector('#preview-dialog');
  const header = document.querySelector('.site-header');
  const updateHeaderHeight = () => document.documentElement.style.setProperty('--header-height', header.getBoundingClientRect().height + 'px');
  new ResizeObserver(updateHeaderHeight).observe(header);
  updateHeaderHeight();
  for (const image of document.querySelectorAll('#hero-image, #preview-image')) image.addEventListener('load', () => {
    image.getAnimations().forEach(animation => animation.cancel());
    if (document.documentElement.classList.contains('motion-enabled')) image.animate([{opacity:.3,transform:'scale(1.015)'},{opacity:1,transform:'scale(1)'}], {duration:420,easing:'cubic-bezier(.22,1,.36,1)'});
  });
  function renderHero() {
    const image = document.querySelector('#hero-image');
    image.src = screenshot(heroView, language); image.alt = text(SCREENS[heroView].alt);
    document.querySelector('#hero-view-title').textContent = text(SCREENS[heroView].title);
    document.querySelector('#hero-panel').setAttribute('aria-labelledby', 'hero-tab-' + heroView);
    document.querySelectorAll('.hero-tabs [data-view]').forEach((button, index) => {
      const selected = button.dataset.view === heroView;
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
      button.querySelector('img').src = `site/screens/thumb-${button.dataset.view}-${language}.png`;
      if (selected) document.querySelector('#hero-view-count').textContent = '0' + (index + 1) + ' / 04';
    });
  }
  function renderPreview() {
    const image = document.querySelector('#preview-image');
    image.src = screenshot(view, language); image.alt = text(SCREENS[view].alt);
    document.querySelector('#preview-caption').textContent = text(SCREENS[view].caption);
    document.querySelector('#preview-panel').setAttribute('aria-labelledby', 'tab-' + view);
    document.querySelectorAll('.preview-tabs [data-view]').forEach(button => { const selected = button.dataset.view === view; button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1; });
  }
  function renderRelease() {
    const release = resolveDownloads(manifest);
    document.querySelector('#release-status').textContent = text(releaseLoading ? 'releaseLoading' : releaseFailed ? 'releaseUnavailable' : !release ? 'releasePending' : Object.keys(release.items).length !== 3 ? 'releasePartial' : release.prerelease ? 'releaseReady' : 'releaseStable');
    document.querySelector('#release-link').href = RELEASES;
    document.querySelector('#release-brand-note').hidden = release?.appName !== 'ZAOWU';
    document.querySelector('[data-copy="portableBody"]').textContent = text(release?.appName === 'ZAOWU' ? 'portableLegacyBody' : 'portableBody');
    document.querySelectorAll('[data-release-version]').forEach(node => { node.textContent = release?.tag || 'v0.19.0'; });
    for (const kind of ['installer','portable','source']) {
      const asset = release?.items[kind];
      document.querySelector(`[data-download="${kind}"]`).href = asset?.url || release?.releaseUrl || RELEASES;
      document.querySelector(`[data-download-label="${kind}"]`).textContent = text(asset ? {installer:'getInstaller',portable:'getPortable',source:'getSource'}[kind] : 'openRelease');
      document.querySelector(`[data-download-size="${kind}"]`).textContent = asset ? (asset.size / 1024 / 1024).toFixed(1) + ' MiB' : '—';
      const checksum = document.querySelector(`[data-checksum="${kind}"]`);
      checksum.href = asset?.checksum || release?.releaseUrl || RELEASES;
      checksum.textContent = text(asset?.checksum ? 'checksum' : 'checksumFallback');
    }
  }
  function render() {
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    document.title = text('title');
    document.querySelector('meta[name="description"]').content = text('description');
    document.querySelector('meta[property="og:title"]').content = text('title');
    document.querySelector('meta[property="og:description"]').content = text('description');
    document.querySelector('meta[property="og:locale"]').content = language === 'en' ? 'en_US' : 'zh_CN';
    document.querySelector('meta[property="og:image:alt"]').content = text('sharingAlt');
    document.querySelector('meta[name="twitter:title"]').content = text('title');
    document.querySelector('meta[name="twitter:description"]').content = text('description');
    document.querySelector('meta[name="twitter:image:alt"]').content = text('sharingAlt');
    const schema = document.querySelector('#software-schema'), application = JSON.parse(schema.textContent);
    application.description = text('description'); schema.textContent = JSON.stringify(application);
    document.querySelector('nav').setAttribute('aria-label', text('navigationLabel'));
    document.querySelector('.integrations').setAttribute('aria-label', text('integrationsLabel'));
    document.querySelector('.preview-tabs').setAttribute('aria-label', text('screenshotsLabel'));
    document.querySelector('.hero-tabs').setAttribute('aria-label', text('heroScreensLabel'));
    dialog.setAttribute('aria-label', text('dialogLabel'));
    document.querySelectorAll('[data-copy]').forEach(node => { node.textContent = text(node.dataset.copy); });
    const toggle = document.querySelector('#language-toggle');
    toggle.textContent = language === 'en' ? '简体中文' : 'English';
    toggle.setAttribute('aria-label', text('switchLanguage'));
    renderHero(); renderPreview(); renderRelease();
    const motion = document.querySelector('#motion-toggle');
    motion.textContent = text(motion.disabled ? 'motionSystem' : document.documentElement.classList.contains('motion-enabled') ? 'motionOn' : 'motionOff');
  }
  document.querySelector('#language-toggle').addEventListener('click', () => { language = language === 'en' ? 'zh' : 'en'; try { localStorage.setItem('zaowu-site-language', language); } catch {} render(); });
  document.querySelectorAll('[data-view]').forEach(button => {
    const select = target => { if (button.closest('.hero-tabs')) { heroView = target.dataset.view; renderHero(); } else { view = target.dataset.view; renderPreview(); } };
    button.addEventListener('click', () => select(button));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...button.closest('[role="tablist"]').querySelectorAll('[data-view]')], index = buttons.indexOf(button);
      const target = buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length];
      select(target); target.focus();
    });
  });
  document.querySelector('#expand-preview').addEventListener('click', () => { const source = document.querySelector('#preview-image'), target = document.querySelector('#dialog-image'); target.src = source.src; target.alt = source.alt; document.querySelector('#original-image').href = source.src; dialog.showModal(); });
  document.querySelector('#close-preview').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
  setupMotion(() => {
    const toggle = document.querySelector('#motion-toggle');
    toggle.textContent = text(toggle.disabled ? 'motionSystem' : document.documentElement.classList.contains('motion-enabled') ? 'motionOn' : 'motionOff');
  });
  render();
  loadRelease(new URL('./release.json', import.meta.url)).then(value => { manifest = value; releaseLoading = false; renderRelease(); }).catch(() => { releaseFailed = true; releaseLoading = false; renderRelease(); });
}
if (typeof document !== 'undefined') start();
