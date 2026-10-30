import PathPicker from './PathPicker';
import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Box, Check, CheckCircle2, ChevronDown, Download, ExternalLink, FileText, Files,
  FolderOpen, History, Image as ImageIcon, Layers3, ListTodo, LoaderCircle, MessageSquare, Music2, Plus,
  PlugZap, RefreshCw, Save, Search, Sparkles, TriangleAlert, Undo2, Upload, X } from 'lucide-react';
import { api, patch, post } from './api';
import Chat from './Chat';
import RunDetails from './RunDetails';
import { clearLocal, loadLocal, saveLocal } from './drafts';
import Tasks from './Tasks';
import Jobs from './Jobs';
import Music from './Music';
import WebUI from './WebUI';
import Modeling from './Modeling';
import Accounts from './Accounts';
import Management from './Management';
import Diagnostics from './Diagnostics';
import Onboarding from './Onboarding';
import Logo from './Logo';
import LanguageSwitch from './LanguageSwitch';
import { CatalogPages, useCatalog } from './Catalog';
import ImportProject, { ExistingProject, categories } from './ProjectIntake';
import ImageComposer, { ArtRecords } from './ImageComposer';
const LazyModelPreview = React.lazy(() => import('./ModelPreview'));
function ModelPreview({ url }: { url: string }) { return <React.Suspense fallback={<span>{tr("载入 3D 查看器…")}</span>}><LazyModelPreview url={url}/></React.Suspense>; }
import './style.css';
import './studio.css';

type Page = 'onboarding' | 'diagnostics' | 'jobs' | 'overview' | 'documents' | 'assets' | 'tasks' | 'music' | 'blender' | 'webui' | 'management' | 'accounts' | 'connections';
type Project = { id: string; name: string; engine: string; root: string; brief: string };
type Data = { project: Project; documents: any[]; assets: any[]; tasks: any[]; messages: any[]; runs: any[]; intake?: any; counts: any; as_of: string };
const statusText: Record<string, string> = { todo: tr("待执行"), running: tr("进行中"), review: tr("待验收"), done: tr("已完成"), blocked: tr("受阻"), cancelled: tr("已取消"), completed: tr("已执行"), failed: tr("失败"), interrupted: tr("已中断") };
const nav: [Page, string, React.ElementType][] = [['overview', tr("项目总览"), Layers3], ['documents', tr("设计资料"), Files], ['assets', tr("资产工作区"), Box], ['tasks', tr("任务看板"), ListTodo], ['jobs', tr("作业中心"), Activity], ['music', tr("音乐工作区"), Music2], ['blender', tr("角色建模"), Box], ['webui', tr("WebUI 绘画"), ImageIcon], ['management', tr("项目留存"), History], ['accounts', tr("账户额度"), Activity], ['connections', tr("模型与引擎"), PlugZap], ['diagnostics', tr("运行诊断"), Activity], ['onboarding', tr("快速上手"), Sparkles]];
const pageAgent = (page: Page) => page === 'music' ? 'music' : page === 'blender' ? 'modeler' : 'director';
const time = (value: string) => new Date(value).toLocaleString(dateLocale, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });

function App() {
  const [boot, setBoot] = useState<any>(null), [projectId, setProjectId] = useState(() => { try { return localStorage.getItem('workbench-project') || ''; } catch { return ''; } });
  const [data, setData] = useState<Data | null>(null), [page, setPage] = useState<Page>(() => { try { const saved = sessionStorage.getItem('workbench-page'); return nav.some(([key]) => key === saved) ? saved as Page : 'overview'; } catch { return 'overview'; } });
  const [creating, setCreating] = useState(false), [importing, setImporting] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false), [codexInfo, setCodexInfo] = useState<any>(null);
  const [attachment, setAttachment] = useState<any>(null), [chatBusy, setChatBusy] = useState(false);
  const [analysisRequest, setAnalysisRequest] = useState<any>(null);
  const pendingActions = useRef(0);
  const [jobTarget, setJobTarget] = useState<any>(null);
  const sectionSequences = useRef<Record<string, number>>({});
  const activeProject = useRef(projectId), refreshSequence = useRef(0);
  activeProject.current = projectId;
  const refreshBoot = async () => { const value = await api('/bootstrap'); setBoot(value); return value; };
  const mergeData = (selected: string, sequence: number, values: any) => {
    if (activeProject.current !== selected) return;
    setData(old => {
      if (!old || old.project.id !== selected) {
        if (!values.project || !values.documents) return old;
        for (const key of Object.keys(values)) sectionSequences.current[selected + key] = sequence;
        return values;
      }
      const next: any = { ...old }; let changed = false;
      for (const [key, value] of Object.entries(values)) if ((sectionSequences.current[selected + key] || 0) <= sequence) {
        sectionSequences.current[selected + key] = sequence;
        if (JSON.stringify(next[key]) !== JSON.stringify(value)) { next[key] = value; changed = true; }
      }
      return changed ? next : old;
    });
  };
  const refreshSections = async (_sections = ['tasks', 'runs', 'assets']) => {
    const selected = projectId, sequence = ++refreshSequence.current;
    if (!selected) return;
    const value = await api(`/projects/${selected}/workspace`);
    mergeData(selected, sequence, value);
  };
  const openJob = (target: any) => { setJobTarget(target); setPage('jobs'); };
  const refresh = async () => {
    const selected = projectId, sequence = ++refreshSequence.current;
    if (!selected) return;
    const value = await api(`/projects/${selected}/workspace`);
    mergeData(selected, sequence, value);
  };
  const run = async (fn: () => Promise<any>, success = '') => {
    setError(''); pendingActions.current += 1; setBusy(true);
    try { const result = await fn(); if (success) setNotice(success); return result; }
    catch (e) { setError((e as Error).message); }
    finally { pendingActions.current -= 1; setBusy(pendingActions.current > 0); }
  };
  useEffect(() => { refreshBoot().then(v => { if (projectId && !v.projects.some((p: Project) => p.id === projectId)) { activeProject.current = ''; setProjectId(''); setError(''); try { localStorage.removeItem('workbench-project'); } catch {} } if (v.show_onboarding) setPage('onboarding'); }).catch(e => setError(e.message)); api('/codex/status').then(setCodexInfo).catch(() => {}); }, []);
  useEffect(() => { setData(null); setAttachment(null); if (projectId) { try { localStorage.setItem('workbench-project', projectId); } catch { setError(tr("浏览器无法记住项目选择，刷新后请重新选择项目")); } refresh().catch(e => { if (activeProject.current === projectId) setError(e.message); }); } }, [projectId]);
  useEffect(() => { try { sessionStorage.setItem('workbench-page', page); } catch {} }, [page]);
  useEffect(() => { if (!notice) return; const id = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(id); }, [notice]);
  const current = boot?.projects?.find((p: Project) => p.id === projectId);
  const analyzeProject = () => run(async () => {
    if (chatBusy) throw new Error(tr("请先等待或停止当前对话"));
    const pid = projectId, result = await post(`/projects/${pid}/intake/analyze`);
    await refresh();
    if (activeProject.current !== pid) return;
    setPage('overview'); setAnalysisRequest({ id: crypto.randomUUID(), pid, message: result.message });
  });
  const finishProject = async (p: Project) => { await refreshBoot(); setProjectId(p.id); setCreating(false); setPage('overview'); };
  const upload = async (file: File) => { const form = new FormData(); form.append('file', file); await api(`/projects/${projectId}/upload`, { method: 'POST', body: form }); await refresh(); };
  const importBackup = async (file: File) => { const form = new FormData(); form.append('file', file); const p = await api('/import-project', { method: 'POST', body: form }); await finishProject(p); setNotice(tr("已恢复为独立项目副本；引擎工程需单独连接")); };
  const actionRunning = data?.runs.some(r => r.status === 'running' && r.kind.startsWith('agent_action:')) || false;
  useEffect(() => { if (!projectId || (!chatBusy && !actionRunning)) return; let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => { try { await refresh(); } catch (e) { if (active) setError((e as Error).message); } if (active) timer = setTimeout(poll, 2500); };
    timer = setTimeout(poll, 2500); return () => { active = false; clearTimeout(timer); };
  }, [projectId, chatBusy, actionRunning]);
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); if (chatBusy && pageAgent(page) !== 'director') setError(tr("对话运行中，请先停止生成再切换负责人")); else setPage('overview'); }}><span className="brand-mark"><Logo/></span><span className="brand-name">{tr("游织工坊")}<small>AI GAME WORKBENCH</small></span></a>
      <div className="project-switch"><FolderOpen size={17}/><select aria-label={tr("当前项目")} disabled={chatBusy} value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">{tr("选择项目")}</option>{boot?.projects?.map((p: Project) => <option key={p.id} value={p.id}>{p.name}</option>)}</select><ChevronDown size={14}/></div>
      <button className="new-project" disabled={chatBusy} onClick={() => setCreating(true)}><Plus size={16}/> {tr("新建游戏项目")}</button>
      <button className="new-project" disabled={chatBusy} onClick={() => setImporting(true)}><FolderOpen size={16}/> {tr("接入已有游戏")}</button>
      <div className="nav-label">{tr("创作空间")}</div>
      <nav>{nav.map(([key, label, Icon]) => <React.Fragment key={key}>{key === 'overview' && <div className="nav-group">{tr("项目管理")}</div>}{key === 'music' && <div className="nav-group">{tr("创作工具")}</div>}{key === 'management' && <div className="nav-group">{tr("工作空间")}</div>}<button disabled={chatBusy && (['connections', 'webui', 'management', 'accounts', 'diagnostics', 'onboarding'].includes(key) || pageAgent(key) !== pageAgent(page))} title={chatBusy ? tr("对话运行中，切换负责人或项目请先停止生成") : label} className={page === key ? 'active' : ''} onClick={() => setPage(key)}><Icon size={18}/><span className="nav-text">{label}</span>{key === 'tasks' && !!data?.counts.tasks && <span className="nav-count">{data.counts.tasks}</span>}</button></React.Fragment>)}</nav>
      <div className="sidebar-bottom"><span className="online-dot"/><div>{tr("本地工作空间")}<small>{tr("文件保存在这台电脑")}</small></div><span className="version">v0.19</span></div>
    </aside>
    <div className="app-main">
      <header className="topbar"><div className="breadcrumb">{tr("工作空间")}<span>/</span> <strong>{current?.name || tr("开始创作")}</strong></div><div className="header-actions"><LanguageSwitch disabled={chatBusy || busy} page={page}/><div className="mobile-project-menu"><select aria-label={tr("切换项目")} disabled={chatBusy} value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">{tr("项目")}</option>{boot?.projects?.map((p: Project) => <option value={p.id} key={p.id}>{p.name}</option>)}</select><button aria-label={tr("新建项目")} disabled={chatBusy} onClick={() => setCreating(true)}><Plus size={16}/></button></div>{current && <span className="engine-badge"><Box size={13}/>{current.engine === 'unreal' ? 'Unreal Engine' : 'Unity'}</span>}<button className="text-button" disabled={chatBusy} onClick={() => setPage('accounts')}>{tr("账户额度")}</button><span className="local-label"><span className="online-dot"/>{tr("本机运行")}</span></div></header>
      {(error || notice) && <div role="status" className={'banner ' + (error ? 'error' : 'success')}>{error ? <TriangleAlert size={16}/> : <Check size={16}/>}<span>{error || notice}</span><button aria-label={tr("关闭通知")} onClick={() => { setError(''); setNotice(''); }}><X size={16}/></button></div>}
      {!boot ? <div className="loading-screen"><LoaderCircle className="spin"/>{tr("正在连接本地工作台…")}</div> : !current && !['connections', 'webui', 'accounts', 'diagnostics', 'onboarding'].includes(page) ? <div className="welcome"><div className="welcome-symbol"><Logo/></div><span className="eyebrow">YOUR NEXT WORLD STARTS HERE</span><h1>{tr("让想法，成为一个世界。")}</h1><p>{tr("从游戏设计到资产制作，与 AI 一起推进你的下一个项目。")}</p><div className="welcome-cards"><div><MessageSquare/><h3>{tr("讨论与设计")}</h3><p>{tr("留下设计依据，让每次交流接续前面的决定。")}</p></div><div><Box/><h3>{tr("查看与编辑资产")}</h3><p>{tr("图片、音乐、模型与引擎资产，在同一处工作。")}</p></div><div><Activity/><h3>{tr("看见真实进度")}</h3><p>{tr("以任务和交付物记录推进，不凭印象估算。")}</p></div></div><button className="primary large" onClick={() => setCreating(true)}><Plus size={18}/>{tr("创建第一个项目")}</button><button className="secondary large" onClick={() => setImporting(true)}><FolderOpen size={18}/>{tr("接入已有游戏项目")}</button><label className="text-button upload-label"><Upload size={15}/>{tr("从备份恢复")}<input type="file" accept=".zip" onChange={e => e.target.files?.[0] && run(() => importBackup(e.target.files![0]))}/></label></div> : <div className={'studio-layout ' + (['connections', 'webui', 'management', 'accounts', 'diagnostics', 'onboarding'].includes(page) ? 'settings-layout' : '')}>
        {!['connections', 'webui', 'management', 'accounts', 'diagnostics', 'onboarding'].includes(page) && data && <Chat analysisRequest={analysisRequest} onAnalysisConsumed={() => setAnalysisRequest(null)} onRunning={setChatBusy} key={projectId + ':' + pageAgent(page)} agent={pageAgent(page)} data={data} providers={boot.providers} codexInfo={codexInfo} attachment={attachment} setAttachment={setAttachment} onRefresh={() => refreshSections(['tasks', 'runs', 'assets', 'documents', 'project'])} onError={setError}/>}
        <main className="workspace">
          <div className="workspace-title"><div><span className="eyebrow">{page === 'connections' ? 'CONNECTIONS' : 'PROJECT WORKSPACE'}</span><h1>{nav.find(n => n[0] === page)?.[1]}</h1></div><div className="toolbar">{current && page !== 'connections' && <button className="icon-button" title={tr("刷新项目")} aria-label={tr("刷新项目")} onClick={() => run(refresh)}><RefreshCw size={16}/></button>}{current && page === 'overview' && <a className="button secondary" href={`/api/projects/${projectId}/export`}><Download size={15}/>{tr("导出备份")}</a>}</div></div>
          {page === 'onboarding' ? <Onboarding run={run} busy={busy} setPage={setPage} onPractice={finishProject} onImport={() => setImporting(true)} hasProject={!!current}/> : page === 'diagnostics' ? <Diagnostics run={run} busy={busy} setPage={setPage} hasProject={!!current}/> : page === 'accounts' ? <Accounts run={run} busy={busy}/> : page === 'webui' ? <WebUI key={projectId} data={data} run={run} busy={busy} refresh={refresh} goAssets={() => setPage('assets')}/> : page === 'connections' ? <Connections boot={boot} codexInfo={codexInfo} setCodexInfo={setCodexInfo} refreshBoot={refreshBoot} data={data} run={run} busy={busy}/> : !data ? <div className="loading-screen"><LoaderCircle className="spin"/>{tr("载入项目…")}</div> : <>
            {page === 'management' && <Management key={projectId} data={data} run={run} busy={busy} refresh={refresh}/>}
            {page === 'overview' && <Overview key={projectId} onAnalyze={analyzeProject} chatBusy={chatBusy} appBusy={busy} onError={setError} data={data} run={run} refresh={refresh} setPage={setPage}/>}
            {page === 'documents' && <Documents key={projectId} data={data} run={run} refresh={refresh} upload={upload}/>}
            {page === 'music' && <Music data={data} run={run} busy={busy} refreshProject={refresh} setPage={setPage}/>}
            {page === 'blender' && <Modeling key={projectId} onError={setError} data={data} run={run} busy={busy} refresh={refresh} onAttach={(a: any) => { if (a) { setAttachment(a); setNotice(tr("参考图已附加，可向角色建模负责人讨论")); } }}/>}
            {page === 'tasks' && <Tasks data={data} run={run} refresh={refreshSections} onError={setError} openJob={openJob} setPage={setPage}/>}
            {page === 'jobs' && <Jobs key={projectId} initialJob={jobTarget} data={data} run={run} busy={busy} refresh={refreshSections} onError={setError} setPage={setPage}/>}

            {page === 'assets' && <Assets key={projectId} onSetup={() => setPage('webui')} data={data} run={run} refresh={refresh} upload={upload} onAttach={(a: any) => { setAttachment(a); setNotice(tr("已附加图片，可在左侧向 AI 提问")); }}/>}
          </>}
        </main>
      </div>}
    </div>
    {importing && <ImportProject close={() => setImporting(false)} finish={async (p: Project) => { await finishProject(p); setImporting(false); }} run={run} busy={busy} projects={boot?.projects || []}/>}
    {creating && <CreateProject close={() => setCreating(false)} finish={finishProject} run={run} busy={busy}/>}
  </div>;
}

function Overview({ data, run, refresh, setPage, onError, onAnalyze, chatBusy, appBusy }: any) {
  const [brief, setBrief] = useState(() => loadLocal('brief:' + data.project.id, data.project.brief));
  const done = data.counts.marked_done;
  return <div className="page-content"><div className="project-hero"><div className="hero-art"><Logo/></div><div className="hero-line"><span className="tag">{data.project.engine === 'unreal' ? 'UNREAL ENGINE' : 'UNITY'}</span><span>{tr("创作进行时")}</span></div><h2>{data.project.name}</h2><p>{tr("每一个决定，都让世界更具体一点。")}</p></div>
    <div className="action-bar"><button className="secondary" onClick={() => setPage('management')}><History size={15}/>{tr("项目快照与 GitHub 留存")}</button></div>
    <div className="stats-grid">{[[FileText, tr("设计资料"), data.counts.documents], [Box, tr("项目资产"), data.counts.assets], [CheckCircle2, tr("标记完成 / 全部任务"), `${done} / ${data.counts.tasks}`]].map(([Icon, label, value]: any) => <div className="stat" key={label}><Icon size={18}/><strong>{value}</strong><span>{label}</span></div>)}</div>
    <p className="hint">{tr("首屏计数未核对交付文件；当前有效验收请打开任务看板查看。")}</p><div className="section-heading"><h2>{tr("项目总纲")}</h2><span>{tr("优先提供给项目负责人")}</span></div><div className="card brief-card"><textarea aria-label={tr("项目总纲")} value={brief} onChange={e => { setBrief(e.target.value); try { saveLocal('brief:' + data.project.id, e.target.value); } catch (e) { onError((e as Error).message); } }} placeholder={tr("游戏类型、核心体验、目标玩家、风格与不可改变的设计规则…")}/><div className="card-footer"><small>{tr("保存后，后续对话会读取这份总纲。")}</small><button className="secondary" onClick={() => run(async () => { await patch(`/projects/${data.project.id}`, { brief }); clearLocal('brief:' + data.project.id); await refresh(); }, tr("总纲已保存"))}><Save size={14}/>{tr("保存总纲")}</button></div></div>
    <ExistingProject data={data} run={run} refresh={refresh} setPage={setPage} onAnalyze={onAnalyze} chatBusy={chatBusy} appBusy={appBusy}/>
    <div className="section-heading"><h2>{tr("最近执行记录")}</h2><button className="text-button" onClick={() => setPage('tasks')}>{tr("查看任务 →")}</button></div><div className="card activity-list">{!data.runs.length ? <Empty icon={Activity} title={tr("还没有执行记录")} text={tr("对话、生成和编辑的实际结果会显示在这里。")}/> : data.runs.slice(0, 6).map((r: any) => <div className="activity-item" key={r.id}><span className={'status-dot ' + r.status}/><div><strong>{serverText(r.detail)}</strong><small>{r.kind} · {time(r.updated)}</small></div><span className={'status ' + r.status}>{statusText[r.status] || r.status}</span><RunDetails run={r} refresh={refresh} onError={onError}/></div>)}</div>
    <div className="path-note"><FolderOpen size={14}/><span>{data.project.root}</span></div>
  </div>;
}

function Documents({ data, run, refresh, upload }: any) {
  const [draftError, setDraftError] = useState(false);
  const [selected, setSelected] = useState(''), [draft, setDraft] = useState<any>(null), [versions, setVersions] = useState<any[] | null>(null);
  const [query, setQuery] = useState(''), [saved, setSaved] = useState<any>(null), [bodyError, setBodyError] = useState('');
  const listing = useCatalog(data.project.id, 'documents', query, '', '', data.as_of);
  useEffect(() => { if (!selected && listing.items[0]) setSelected(listing.items[0].id); }, [listing.items]);
  useEffect(() => { let active = true; setVersions(null); setBodyError(''); if (selected) api(`/projects/${data.project.id}/documents/${selected}`).then(value => { if (active) { setSaved(value); setDraft(loadLocal('document:' + selected, value)); } }).catch(e => { if (active) setBodyError(e.message); }); return () => { active = false; }; }, [selected, data.as_of]);
  const editDraft = (value: any) => { setDraft(value); try { saveLocal('document:' + value.id, value); setDraftError(false); } catch (e) { setDraftError(true); run(async () => { throw e; }); } };
  const dirty = draft && saved && ['title', 'content', 'authority'].some(k => draft[k] !== saved[k]);
  const create = () => run(async () => { const d = await post(`/projects/${data.project.id}/documents`, { title: tr("新的设计文档"), content: '' }); await refresh(); setSelected(d.id); });
  return <div className="page-content documents-page"><div className="action-bar"><button className="primary" onClick={create}><Plus size={15}/>{tr("新建文档")}</button><label className="button secondary upload-label"><Upload size={15}/>{tr("导入资料")}<input type="file" accept=".md,.txt" onChange={e => e.target.files?.[0] && run(() => upload(e.target.files![0]))}/></label></div>
    <input aria-label={tr("搜索设计资料")} placeholder={tr("搜索全部设计标题与正文")} value={query} onChange={e => setQuery(e.target.value)}/><CatalogPages catalog={listing}/>{bodyError && <p role="alert">{bodyError}</p>}<div className="document-tabs">{listing.items.map((d: any) => <button disabled={listing.loading} key={d.id} className={selected === d.id ? 'selected' : ''} onClick={() => setSelected(d.id)}><FileText size={14}/>{d.title}<span className={'doc-state ' + d.authority}>{d.authority === 'approved' ? tr("正式") : d.authority === 'archived' ? tr("废弃") : tr("草稿")}</span></button>)}</div>
    {draft?.id === selected ? <div className="card document-editor"><div className="document-meta"><input aria-label={tr("文档标题")} value={draft.title} onChange={e => editDraft({ ...draft, title: e.target.value })}/><select aria-label={tr("文档权威状态")} value={draft.authority} onChange={e => editDraft({ ...draft, authority: e.target.value })}><option value="draft">{tr("待定草稿")}</option><option value="approved">{tr("正式设计")}</option><option value="archived">{tr("已废弃")}</option></select></div><textarea className="document-text" aria-label={tr("文档内容")} value={draft.content} onChange={e => editDraft({ ...draft, content: e.target.value })} placeholder={tr("支持 Markdown 内容。AI 起草内容会先保存为草稿。")}/><div className="draft-state">{draftError ? tr("草稿未能保存，请复制内容后再离开") : dirty ? tr("有未提交修改 · 已保存在此浏览器") : tr("已与项目版本同步")}{draft.revision !== saved?.revision && <span> {tr("· 项目版本已更新，提交时会检查冲突")}</span>}</div><div className="card-footer"><button className="text-button" onClick={() => run(async () => setVersions(await api(`/documents/${draft.id}/versions`)))}><History size={14}/>{tr("历史版本 · v")}{draft.revision}</button><button className="primary" onClick={() => run(async () => { const value = await patch(`/documents/${draft.id}`, draft); clearLocal('document:' + draft.id); setDraft(value); await refresh(); }, tr("文档版本已保存"))}><Save size={14}/>{tr("保存新版本")}</button></div>{versions && <div className="versions">{!versions.length ? <small>{tr("保存修改后会生成历史记录。")}</small> : versions.map(v => <button key={v.revision} onClick={() => { editDraft({ ...draft, content: v.content, title: v.title, authority: v.authority }); setVersions(null); }}><Undo2 size={13}/>{tr("载入 v")}{v.revision} {tr("内容 ·")}{time(v.created)}</button>)}</div>}</div> : selected ? <p>{tr("正在读取所选文档…")}</p> : <Empty icon={Files} title={tr("建立项目的共同记忆")} text={tr("导入已有策划，或让左侧项目负责人起草一份文档。")}/>}
  </div>;
}

function Assets({ data, run, refresh, upload, onAttach, onSetup }: any) {
  const [filter, setFilter] = useState('all'), [query, setQuery] = useState(''), [selected, setSelected] = useState<any>(null);
  const [info, setInfo] = useState<any>(null), [width, setWidth] = useState(''), [height, setHeight] = useState('');
  const [engineResult, setEngineResult] = useState<any>(null);
  const [start, setStart] = useState('0'), [end, setEnd] = useState('1');
  const [color, setColor] = useState('#b1473d'), [parameter, setParameter] = useState(data.project.engine === 'unity' ? '_Color' : 'Tint');
  useEffect(() => {
    let cancelled = false;
    setInfo(null);
    if (selected) api(`/assets/${selected.id}/info`).then(v => {
      if (cancelled) return;
      setInfo(v); setWidth(String(v.width || '')); setHeight(String(v.height || '')); setEnd(String(v.duration || 1)); setStart('0');
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [selected]);
  const [category, setCategory] = useState('');
  const listing = useCatalog(data.project.id, 'assets', query, filter === 'all' ? '' : filter, category, data.as_of);
  const visible = listing.items;
  const enginePath = selected ? (data.project.engine === 'unreal' ? '/Game/' + selected.source.slice(data.project.root.length + 1).replace(/^Content[\\/]/, '').replace(/\\/g, '/').replace(/\.uasset$/i, '') : selected.source.slice(data.project.root.length + 1).replace(/\\/g, '/')) : '';
  const engineOp = (op: string, extra: any = {}) => run(async () => { const r = await post(`/projects/${data.project.id}/engine/command`, { op, path: enginePath, ...extra }); setEngineResult(r); if (selected) setInfo(await api(`/assets/${selected.id}/info`)); await refresh(); });
  return <div className="page-content"><div className="action-bar"><label className="button primary upload-label"><Upload size={15}/>{tr("导入资产")}<input type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.wav,.mp3,.ogg,.glb,.blend,.fbx,.uasset,.prefab,.mat" onChange={e => e.target.files?.[0] && run(() => upload(e.target.files![0]))}/></label><button className="secondary" onClick={() => run(async () => { const r = await post(`/projects/${data.project.id}/scan`); await refresh(); return r; }, tr("扫描完成；原生资产需编辑器连接才能进一步操作"))}><RefreshCw size={15}/>{tr("扫描工程")}</button></div>
    <div className="asset-filters"><div className="segments">{[['all',tr("全部")],['image',tr("图片")],['audio',tr("音频")],['model','3D'],['blender','Blender'],['source',tr("源文件")],['native',tr("引擎")]].map(([key, label]) => <button key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div><select aria-label={tr("项目资产分类")} value={category} onChange={e => setCategory(e.target.value)}><option value="">{tr("全部用途")}</option>{Object.entries(categories).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select><div className="search-input"><Search size={14}/><input aria-label={tr("搜索资产")} placeholder={tr("搜索资产")} value={query} onChange={e => setQuery(e.target.value)}/></div></div>
    {!visible.length ? <Empty icon={Box} title={tr("资产从这里开始积累")} text={tr("导入图片、音乐或 GLB 模型，也可以扫描已有引擎工程。")}/> : <div className="asset-grid">{visible.map((a: any) => <button disabled={listing.loading} className="asset-card" key={a.id} onClick={() => { setSelected(a); setEngineResult(null); }}><div className={'asset-thumbnail ' + a.kind}>{a.kind === 'image' ? <img src={`/api/assets/${a.id}/file?v=${encodeURIComponent(a.active)}`} alt={a.name} loading="lazy"/> : a.kind === 'audio' ? <Music2 size={34}/> : <Box size={34}/>}<span>{a.kind === 'image' ? 'IMAGE' : a.kind === 'audio' ? 'AUDIO' : a.kind === 'model' ? '3D MODEL' : a.kind === 'blender' ? 'BLENDER SOURCE' : a.kind === 'source' ? 'SOURCE ASSET' : 'ENGINE ASSET'}</span></div><strong>{a.name}</strong><small>{a.relative_path || time(a.created)}{a.source_status === 'missing' ? tr(" · 原文件缺失") : a.source_status === 'unseen' ? tr(" · 本次未扫描到") : ''}</small></button>)}</div>}
    <CatalogPages catalog={listing}/>
    <div className="section-heading"><h2>{tr("美术创作")}</h2><span>{tr("选择 OpenAI 或本机 WebUI")}</span></div><div className="card generation-card"><ImageComposer data={data} run={run} refresh={refresh} onSetup={onSetup}/></div>
    <div className="music-note"><Music2 size={18}/><div><strong>{tr("音乐创作 · SUNO")}</strong><p>{tr("已提供独立音乐工作区，通过 Suno.cn Skill 保存方案、确认提交与查询结果。")}</p></div><a href="https://www.suno.cn/" target="_blank" rel="noreferrer" className="text-button">Suno.cn <ExternalLink size={13}/></a></div>
    {selected && <div className="modal-overlay"><section className="modal asset-modal"><div className="modal-heading"><div><span className="eyebrow">ASSET INSPECTOR</span><h2>{selected.name}</h2></div><button aria-label={tr("关闭资产")} className="icon-button" onClick={() => setSelected(null)}><X size={20}/></button></div><div className="asset-inspector"><div className="preview-canvas">{selected.kind === 'image' ? <img src={`/api/assets/${selected.id}/file?v=${encodeURIComponent(selected.active)}`} alt={selected.name}/> : selected.kind === 'audio' ? <div className="audio-preview"><Music2 size={64}/><audio controls src={`/api/assets/${selected.id}/file?v=${encodeURIComponent(selected.active)}`}/></div> : selected.kind === 'model' ? <ModelPreview url={`/api/assets/${selected.id}/file`}/> : engineResult?.preview_asset_id ? <img src={`/api/assets/${engineResult.preview_asset_id}/file`} alt={tr("编辑器返回的预览")}/> : <div className="native-preview"><Box size={56}/><p>{selected.kind === 'blender' ? tr("Blender 可编辑源文件") : selected.kind === 'source' ? tr("创作源文件") : tr("引擎原生资产")}</p><small>{selected.kind === 'blender' ? tr("在角色建模页查看配套 GLB，下载源文件后可在 Blender 中编辑。") : selected.kind === 'source' ? tr("已登记与分类，可下载后使用对应创作软件编辑；工作台暂不提供此格式的内嵌预览。") : tr("连接编辑器后读取属性或获取已支持的预览。")}</small></div>}</div><div className="asset-properties"><h3>{tr("资产信息")}</h3><dl><dt>{tr("类型")}</dt><dd>{selected.kind}</dd><dt>{tr("大小")}</dt><dd>{info ? (info.bytes / 1024).toFixed(1) + ' KB' : tr("读取中")}</dd>{info?.width && <><dt>{tr("尺寸")}</dt><dd>{info.width} × {info.height}</dd></>}</dl>
      {selected.kind === 'image' && <><button className="secondary full-width" onClick={() => { onAttach(selected); setSelected(null); }}><Sparkles size={14}/>{tr("交给 AI 查看")}</button><h3>{tr("图片编辑")}</h3><div className="dimension-inputs"><label>{tr("宽")}<input aria-label={tr("图片宽度")} type="number" min="1" max="8192" value={width} onChange={e => setWidth(e.target.value)}/></label><span>×</span><label>{tr("高")}<input aria-label={tr("图片高度")} type="number" min="1" max="8192" value={height} onChange={e => setHeight(e.target.value)}/></label></div><button className="primary full-width" disabled={!info} onClick={() => run(async () => { const a = await post(`/assets/${selected.id}/edit`, { width: Number(width), height: Number(height), expected_hash: info.hash }); setSelected(a); await refresh(); }, tr("新版本已保存，原始文件未覆盖"))}><Save size={14}/>{tr("保存尺寸修改")}</button><button className="secondary full-width" disabled={!info} onClick={() => run(async () => { const a = await post(`/assets/${selected.id}/edit`, { flip: true, expected_hash: info.hash }); setSelected(a); await refresh(); })}>{tr("水平翻转并保存")}</button><h3>{tr("AI 图片编辑")}</h3><ImageComposer key={selected.id} data={data} run={run} refresh={refresh} asset={selected} info={info} onResult={setSelected} onSetup={() => { setSelected(null); onSetup(); }}/>
<h3>{tr("版本记录")}</h3>{info?.versions.map((v: any, index: number) => <button className="version-item" key={index} onClick={() => run(async () => { const a = await post(`/assets/${selected.id}/restore`, { index }); setSelected(a); await refresh(); }, tr("已切换资产版本"))}><Undo2 size={13}/>{index === 0 ? tr("原始版本") : tr("版本 {0}", index + 1)}<small>{v.label}</small></button>)}</>}
      {selected.kind === 'audio' && <><h3>{tr("音频裁剪 · 16 位 PCM WAV")}</h3><div className="dimension-inputs"><label>{tr("起点（秒）")}<input type="number" aria-label={tr("音频裁剪起点")} min="0" step="0.1" value={start} onChange={e => setStart(e.target.value)}/></label><label>{tr("终点（秒）")}<input type="number" aria-label={tr("音频裁剪终点")} min="0" step="0.1" value={end} onChange={e => setEnd(e.target.value)}/></label></div><button className="primary full-width" disabled={!info?.duration} onClick={() => run(async () => { const a = await post(`/assets/${selected.id}/edit-audio`, {start: Number(start), end: Number(end), fade: true, expected_hash: info.hash}); setSelected(a); await refresh(); }, tr("已保存裁剪版本，原始音频未覆盖"))}>{tr("裁剪并加入短淡入淡出")}</button><h3>{tr("版本记录")}</h3>{info?.versions.map((v: any, index: number) => <button className="version-item" key={index} onClick={() => run(async () => { setSelected(await post(`/assets/${selected.id}/restore`, {index})); await refresh(); })}><Undo2 size={13}/>{v.label}</button>)}</>}
      {selected.kind === 'native' && <><p className="hint break">{enginePath}</p><button className="secondary full-width" onClick={() => engineOp('inspect')}>{tr("读取原生属性")}</button><button className="secondary full-width" onClick={() => engineOp('preview')}>{tr("获取编辑器预览")}</button><h3>{tr("材质颜色参数")}</h3><input aria-label={tr("材质参数名称")} value={parameter} onChange={e => setParameter(e.target.value)}/><input aria-label={tr("材质颜色")} type="color" value={color} onChange={e => setColor(e.target.value)}/><button className="primary full-width" disabled={!info} onClick={() => engineOp('set_material_color', { name: parameter, color: [1,3,5].map(i => parseInt(color.slice(i,i+2), 16)/255).concat(1), asset_id: selected.id, expected_hash: info.hash })}>{tr("备份并应用到引擎")}</button><p className="hint">{tr("仅支持连接器公布的资产与参数。修改前会创建引擎内备份。")}</p>{engineResult && <pre className="engine-result">{JSON.stringify(engineResult, null, 2)}</pre>}</>}
      {!!info?.generations?.length && <><h3>{tr("创作参数与来源")}</h3><ArtRecords records={info.generations}/></>}<a className="button secondary full-width" href={`/api/assets/${selected.id}/file`} download={selected.name}><Download size={14}/>{tr("下载当前文件")}</a></div></div></section></div>}
  </div>;
}

function Connections({ boot, codexInfo, setCodexInfo, refreshBoot, data, run, busy }: any) {
  const [environment, setEnvironment] = useState<any>(null), [engine, setEngine] = useState<any>(null);
  useEffect(() => { api('/environment').then(setEnvironment).catch(() => {}); }, []);
  const [policy, setPolicy] = useState<any>(null), [role, setRole] = useState('director'), [mode, setMode] = useState('discussion');
  useEffect(() => { api('/mcp/policy').then(setPolicy).catch(() => {}); }, []);
  const checkCodex = () => run(async () => { const r = await api('/codex/status'); setCodexInfo(r); if (!r.available) throw new Error(r.error); });
  return <div className="page-content settings-content"><p className="page-description">{tr("为项目连接模型与编辑器。身份登录、请求成功和引擎连接分别验证。")}</p><section className="card connection-card"><div className="connection-heading"><span className="connection-icon"><Sparkles/></span><div><h2>{tr("Codex 会员连接")}</h2><p>{tr("使用本机官方 Codex App Server")}</p></div><span className={'status ' + (codexInfo?.account ? 'done' : 'blocked')}>{codexInfo?.account ? tr("已登录 · 推理待实际任务验证") : tr("待连接")}</span></div><div className="connection-body"><p>{codexInfo?.account ? tr("登录方式：{0}。可用模型与限额以官方账号权限为准。", codexInfo.account.type || 'ChatGPT') : codexInfo?.error || tr("点击检查，读取本机 Codex 的登录状态。")}</p><div className="action-bar"><button className="primary" disabled={busy} onClick={checkCodex}><RefreshCw size={14}/>{tr("检查连接")}</button><button className="secondary" disabled={busy} onClick={() => run(async () => { const login = await post('/codex/login'); if (login.authUrl) window.open(login.authUrl, '_blank', 'noopener,noreferrer'); }, tr("请在浏览器完成官方登录，然后重新检查连接"))}>{tr("通过 ChatGPT 登录")}<ExternalLink size={13}/></button></div></div></section>
    <section className="card connection-card"><div className="connection-heading"><span className="connection-icon"><PlugZap/></span><div><h2>{tr("MCP 工具与权限")}</h2><p>{tr("每轮核验运行时目录；额外工具会阻止启动")}</p></div></div><div className="connection-body"><div className="action-bar"><select aria-label={tr("工具角色")} value={role} onChange={e => setRole(e.target.value)}><option value="director">{tr("项目负责人")}</option><option value="music">{tr("音乐负责人")}</option><option value="modeler">{tr("角色建模负责人")}</option></select><select aria-label={tr("工具模式")} value={mode} onChange={e => setMode(e.target.value)}><option value="discussion">{tr("讨论")}</option><option value="execute">{tr("执行")}</option></select><button className="secondary" disabled={busy || !data} onClick={() => run(async () => { await post(`/projects/${data.project.id}/mcp/check`, { agent: role, execute: mode === 'execute' }); setPolicy(await api('/mcp/policy')); }, tr("已核验实际工具目录，未发起模型推理"))}>{tr("核验运行时工具")}</button></div><ul className="tool-catalog">{policy?.profiles?.[role]?.[mode]?.map((t: any) => <li key={t.name}><strong>{t.name}</strong><small>{serverText(t.description)}</small></li>)}</ul><p className="hint">{policy?.last_check?.verified ? tr("最近核验通过（{0} · {1}）· {2} 个工具", policy.last_check.agent === 'music' ? tr("音乐负责人") : policy.last_check.agent === 'modeler' ? tr("角色建模负责人") : tr("项目负责人"), policy.last_check.mode === 'execute' ? tr("执行") : tr("讨论"), policy.last_check.tools?.length) : tr("尚无通过的运行时核验")}{tr("。本机单用户使用；暂不开放自定义外部 MCP 注册。")}</p></div></section>
    {['openai', 'deepseek'].map(p => <ProviderCard key={p} provider={p} config={boot.providers[p]} imageModel={boot.image_model} run={run} refresh={refreshBoot} busy={busy}/>)}
    <section className="card connection-card"><div className="connection-heading"><span className="connection-icon"><Box/></span><div><h2>{tr("引擎与本机环境")}</h2><p>{tr("按具体版本验证，连接器操作在编辑器中执行")}</p></div></div><div className="connection-body">{environment?.engines?.map((e: any) => <div className="environment-item" key={e.executable}><CheckCircle2 size={15}/><span>{e.engine === 'unreal' ? 'Unreal Engine' : 'Unity'} {e.version}</span><small>{tr("已发现安装")}</small></div>)}{!environment?.engines?.length && <p>{tr("未在常见位置发现编辑器，可先绑定已有工程。")}</p>}{data ? <><div className="path-note break"><FolderOpen size={14}/>{data.project.root}</div><div className="action-bar"><button className="secondary" disabled={busy} onClick={() => { if (window.confirm(tr("将向所选工程安装工作台连接器；虚幻工程描述文件会先备份。继续？"))) run(async () => { const r = await post(`/projects/${data.project.id}/engine/install`); setEngine(r); }); }}>{tr("安装到当前工程")}</button><button className="primary" disabled={busy} onClick={() => run(async () => setEngine(await post(`/projects/${data.project.id}/engine/command`, { op: 'status' })))}><PlugZap size={14}/>{tr("验证编辑器连接")}</button></div>{engine && <pre className="engine-result">{JSON.stringify(engine, null, 2)}</pre>}</> : <p>{tr("创建并绑定一个工程后，可安装连接器。")}</p>}</div></section><p className="hint">{tr("本版桌面鼠标键盘控制尚未交付；当前本机执行通过 Codex 项目工具和编辑器连接器完成。")}</p></div>;
}

function ProviderCard({ provider, config, imageModel, run, refresh, busy }: any) {
  const [key, setKey] = useState(''), [model, setModel] = useState(config.model || ''), [image, setImage] = useState(imageModel || ''), [models, setModels] = useState<any[]>([]);
  return <section className="card connection-card"><div className="connection-heading"><span className="connection-icon"><PlugZap/></span><div><h2>{provider === 'openai' ? 'OpenAI API' : 'DeepSeek API'}</h2><p>{tr("独立 API Key · 按供应商实际用量计费")}</p></div><span className={'status ' + (config.configured ? 'review' : 'blocked')}>{config.verified ? tr("此模型曾完成文本推理") : config.configured ? tr("已配置 · 待推理验证") : tr("未配置")}</span></div><div className="connection-body form-grid"><label>API Key<input type="password" autoComplete="off" placeholder={config.configured ? tr("已保存，留空保持不变") : tr("仅保存在本机，Windows 加密保护")} value={key} onChange={e => setKey(e.target.value)}/></label><label>{tr("文本模型 ID")}<input list={'models-' + provider} placeholder={tr("获取列表后选择，或填写模型 ID")} value={model} onChange={e => setModel(e.target.value)}/><datalist id={'models-' + provider}>{models.map((m: any) => <option key={m.id} value={m.id}/>)}</datalist></label>{provider === 'openai' && <label>{tr("图像模型 ID")}<input placeholder={tr("填写账号可用的图像模型 ID")} value={image} onChange={e => setImage(e.target.value)}/></label>}<div className="action-bar"><button className="primary" disabled={busy} onClick={() => run(async () => { await api(`/providers/${provider}`, { method: 'PUT', body: JSON.stringify({ key, model, image_model: image }) }); setKey(''); await refresh(); }, tr("连接配置已保存"))}><Save size={14}/>{tr("保存配置")}</button><button className="secondary" disabled={busy || !config.configured} onClick={() => run(async () => setModels((await post(`/providers/${provider}/test`)).models), tr("模型列表读取成功；不代表所有模型已通过推理验证"))}>{tr("获取模型列表")}</button></div></div></section>;
}

function CreateProject({ close, finish, run, busy }: any) {
  const [name, setName] = useState(''), [engine, setEngine] = useState('unreal'), [root, setRoot] = useState('');
  return <div className="modal-overlay"><form className="modal create-modal" onSubmit={e => { e.preventDefault(); run(async () => { await finish(await post('/projects', { name, engine, root })); }); }}><div className="modal-heading"><div><span className="eyebrow">NEW PROJECT</span><h2>{tr("新的世界，从这里开始。")}</h2></div><button type="button" className="icon-button" aria-label={tr("关闭新建项目")} onClick={close}><X size={20}/></button></div><label>{tr("项目名称")}<input autoFocus required maxLength={100} value={name} onChange={e => setName(e.target.value)} placeholder={tr("给你的游戏取一个名字")}/></label><label>{tr("开发引擎")}</label><div className="engine-options">{[['unreal', 'Unreal Engine', tr("虚幻引擎")], ['unity', 'Unity', tr("Unity 编辑器")]].map(([key, title, subtitle]) => <button type="button" key={key} className={engine === key ? 'selected' : ''} onClick={() => setEngine(key)}><Box size={24}/><strong>{title}</strong><small>{subtitle}</small>{engine === key && <Check size={15}/>}</button>)}</div><label>{tr("已有工程目录（可选）")}<input value={root} onChange={e => setRoot(e.target.value)} placeholder={tr("例如 E:\\Games\\MyGame")}/><PathPicker purpose="project" value={root} change={setRoot} run={run} disabled={busy}/></label><p className="hint">{tr("留空会创建独立的资料工作区。若要自动接入现有资料与资产，请使用左侧“接入已有游戏”；编辑器内操作仍需另行连接。")}</p><button className="primary full-width" disabled={busy || !name.trim()} type="submit">{busy ? <LoaderCircle size={16} className="spin"/> : <Plus size={16}/>}{tr("创建项目")}</button></form></div>;
}

function Empty({ icon: Icon, title, text }: { icon: React.ElementType; title: string; text: string }) {
  return <div className="empty"><span><Icon size={26}/></span><h3>{title}</h3><p>{text}</p></div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
