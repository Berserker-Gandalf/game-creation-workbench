import PathPicker from './PathPicker';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { Box, Check, FileText, FolderOpen, LoaderCircle, RefreshCw, Search, X } from 'lucide-react';
import { api, post } from './api';
import ProjectMaintenance from './ProjectMaintenance';

export const categories: Record<string, string> = { design: tr("设计资料"), code: tr("代码"), config: tr("工程配置"), image: tr("图片 / 贴图"), model: tr("模型"), audio: tr("音频"), scene: tr("关卡 / 场景"), prefab: tr("预制体"), material: tr("材质"), animation: tr("动画"), native: tr("其他原生资产"), other: tr("其他文件") };

export default function ImportProject({ close, finish, run, busy, projects, project }: any) {
  const [root, setRoot] = useState(''), [name, setName] = useState(''), [engine, setEngine] = useState('unreal');
  const [additional, setAdditional] = useState('');
  const [scanning, setScanning] = useState(false);
  const [preview, setPreview] = useState<any>(null), [selected, setSelected] = useState<string[]>([]);
  const scan = () => run(async () => {
    setScanning(true);
    try {
    setPreview(null);
    const extras = additional.split(/\r?\n/).map(p => p.trim()).filter(Boolean);
    const result = await post(project ? `/projects/${project.id}/intake/sources/preview` : '/project-intake/preview', { roots: project ? extras : [root, ...extras] });
    setPreview(result); setRoot(result.root); setSelected(result.suggested_documents);
    setName(result.root.split(/[\\/]/).filter(Boolean).pop() || tr("已有游戏"));
    if (result.engine) setEngine(result.engine);
    } finally { setScanning(false); }
  });
  const existing = !project && preview && projects.find((p: any) => p.id === preview.existing_project_id);
  return <div className="modal-overlay"><section className="modal intake-modal">
    <div className="modal-heading"><div><span className="eyebrow">CONTINUE YOUR GAME</span><h2>{project ? tr("补充项目来源目录") : tr("接续你已经创造的世界。")}</h2></div><button disabled={busy} aria-label={tr("关闭接入项目")} className="icon-button" onClick={close}><X size={20}/></button></div>
    <p className="hint">{tr("一个主工程连接引擎，其他目录作为同一游戏的资料与资产来源，合计最多8个。资产原位登记，勾选正文会提供给所选对话模型；接入不会移动文件或运行工程。")}</p>
    {project ? <p className="hint">{tr("主工程：")}{project.root}{tr("。已有来源继续保留；本次只增加目录。")}</p> : <label>{tr("主工程文件夹")}<input aria-label={tr("游戏项目文件夹")} disabled={busy} value={root} onChange={e => { setRoot(e.target.value); setPreview(null); }} placeholder={tr("例如 E:\\Games\\MyGame")} onKeyDown={e => { if (e.key === 'Enter' && root.trim() && !busy) scan(); }}/><PathPicker purpose="project" value={root} disabled={busy} run={run} change={path => { setRoot(path); setPreview(null); }}/></label>}
    <label>{tr("附加资料 / 资产目录（每行一个）")}<textarea aria-label={tr("附加项目文件夹")} disabled={busy} value={additional} onChange={e => { setAdditional(e.target.value); setPreview(null); }} placeholder={tr("例如 E:\\GameArt\nE:\\GameDesign")}/><PathPicker purpose="source" disabled={busy} run={run} change={path => { setAdditional(old => [...new Set([...old.split(/\r?\n/).filter(Boolean), path])].join("\n")); setPreview(null); }}/></label>
    <button className="secondary" disabled={busy || (project ? !additional.trim() : !root.trim())} onClick={scan}>{busy ? <LoaderCircle className="spin" size={15}/> : <Search size={15}/>}{tr("扫描并预览")}</button>
    {scanning && <p className="hint" role="status">{tr("正在读取目录与资料；扫描预算约 20 秒，大型或网络目录可能更久。不调用收费模型。")}</p>}
    {preview && <>
      <div className="intake-stats"><span>{preview.engine === 'unreal' ? 'Unreal Engine' : preview.engine === 'unity' ? 'Unity' : tr("待选择引擎")} {preview.engine_version}</span><strong>{preview.file_count} {tr("个已扫描文件")}</strong></div>
      <div className="source-roots">{preview.roots?.map((r: any) => <p key={r.id}><strong>{r.id === 'primary' ? tr("主工程") : tr("附加来源")}</strong><code>{r.path}</code></p>)}</div>
      <div className="intake-counts">{Object.entries(preview.counts).map(([k, count]: any) => <span key={k}>{categories[k] || k}<strong>{count}</strong></span>)}</div>
      {preview.warnings.map((w: string) => <p className="intake-warning" key={w}>{w}</p>)}
      {!project && !preview.engine && !!preview.project_candidates.length && <details><summary>{tr("发现的工程位置（可选择后重新扫描）")}</summary>{preview.project_candidates.map((p: any) => <button key={p.directory + p.engine} className="intake-candidate" disabled={busy} onClick={() => { setRoot(p.directory); setPreview(null); }}>{p.engine === 'unreal' ? 'Unreal' : 'Unity'} · {p.directory}</button>)}</details>}
      {existing ? <div className="card intake-existing"><p>{tr("此目录已接入：")}{existing.name}</p><button className="primary" disabled={busy} onClick={() => finish(existing)}><FolderOpen size={15}/>{tr("打开已有工作台项目")}</button></div> : <>
        {!project && <div className="intake-fields"><label>{tr("工作台项目名称")}<input aria-label={tr("接入项目名称")} disabled={busy} value={name} maxLength={100} onChange={e => setName(e.target.value)}/></label><label>{tr("开发引擎")}<select aria-label={tr("接入项目引擎")} disabled={busy || !!preview.engine} value={engine} onChange={e => setEngine(e.target.value)}><option value="unreal">Unreal Engine</option><option value="unity">Unity</option></select></label></div>}
        <div className="section-heading"><h3>{tr("接入设计与开发资料")}</h3><span>{selected.length} {tr("份已选")}</span></div><p className="hint">{tr("只将勾选的正文纳入项目上下文，均先标为待定。无设计资料时，仅能依据文件与代码结构形成有限判断。")}</p>
        <div className="intake-documents">{preview.documents.length ? preview.documents.map((d: any) => <label key={d.path}><input type="checkbox" disabled={busy} checked={selected.includes(d.path)} onChange={e => setSelected(old => e.target.checked ? [...old, d.path] : old.filter(p => p !== d.path))}/><span><strong>{d.path}</strong><small>{d.chars} {tr("字符")}</small><p>{d.excerpt}</p></span></label>) : <p className="hint">{tr("没有可自动读取的 Markdown / TXT / RST 文档。可稍后手动导入设计资料。")}</p>}</div>
        <details className="intake-samples"><summary>{tr("查看扫描样本与分类依据")}</summary><p className="hint">{tr("分类按扩展名和目录推测，未运行引擎、未解析蓝图逻辑。")}</p>{preview.samples.map((f: any) => <div key={f.path}><span>{categories[f.category]}</span><code>{f.path}</code></div>)}</details>
        <button className="primary full-width" disabled={busy || (!project && !name.trim())} onClick={() => run(async () => { const result = await post(project ? `/projects/${project.id}/intake/sources` : '/project-intake/attach', { preview_id: preview.id, name, engine, documents: selected }); await finish(project || result); })}><Check size={15}/>{project ? tr("确认增加来源并更新分类") : tr("接入目录并建立项目状态摘要")}</button>
      </>}
    </>}
  </section></div>;
}

export function ExistingProject({ data, run, refresh, setPage, onAnalyze, chatBusy, appBusy }: any) {
  const [files, setFiles] = useState<any>(null), [query, setQuery] = useState(''), [category, setCategory] = useState(''), [offset, setOffset] = useState(0), [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const state = data.intake, pid = data.project.id;
  useEffect(() => {
    if (!state || !inventoryOpen) return;
    let active = true;
    api(`/projects/${pid}/intake/files?q=${encodeURIComponent(query)}&category=${category}&offset=${offset}`).then(v => { if (active) setFiles(v); }).catch(e => { if (active) run(async () => { throw e; }); });
    return () => { active = false; };
  }, [pid, state?.updated, query, category, offset, inventoryOpen]);
  const rescan = () => run(async () => {
    setBusy(true);
    try { await post(`/projects/${pid}/intake/refresh`); await refresh(); }
    finally { setBusy(false); }
  }, tr("原项目清单与状态依据已更新；未改写工程文件"));
  if (!state) return <section className="card intake-overview"><h2>{tr("已有目录的项目接入")}</h2><p className="hint">{tr("如该项目绑定了已有游戏文件夹，可读取资产、设计资料与结构线索。工程文件保持原位。")}</p><button className="secondary" disabled={busy} onClick={rescan}><FolderOpen size={15}/>{tr("扫描并建立接入摘要")}</button></section>;
  const report = state.report;
  return <section className="card intake-overview">
    <div className="section-heading"><h2>{tr("原项目接入与现状")}</h2><span className="status review">{report.restored_snapshot ? tr("恢复的历史快照") : tr("已索引 · 运行待核实")}</span></div>
    <p className="hint">{new Date(state.updated).toLocaleString(dateLocale)} · {report.engine === 'unreal' ? 'Unreal' : 'Unity'} {report.engine_version} · {report.file_count} {tr("个文件 ·")}{report.registered_assets} {tr("个")}{report.restored_snapshot ? tr("历史登记资产") : tr("原位资产")}</p>
    <div className="source-roots">{report.roots?.map((r: any) => <p key={r.id}><strong>{r.id === 'primary' ? tr("主工程") : tr("附加来源")}</strong><code>{r.path}</code></p>)}</div>
    <div className="intake-counts">{Object.entries(report.counts).map(([k, n]: any) => <button key={k} onClick={() => { setCategory(k); setOffset(0); }}>{categories[k] || k}<strong>{n}</strong></button>)}</div>
    <p className="intake-warning">{tr("以下是文件、原文陈述和代码结构的依据。工作台未运行原工程，未据此判定功能完成或填写完成率。")}</p>
    {!!report.design_topics.length && <div className="intake-topics"><h3>{tr("设计主题")}</h3>{report.design_topics.slice(0, 8).map((t: any, i: number) => <p key={i}>{t.text.replace(/^\s*#+\s*/, '')}<small>{t.path}:{t.line}</small></p>)}</div>}
    {!!report.claims.length && <details><summary>{tr("原文记录的开发进度（待核实）")}</summary>{report.claims.map((claim: any, i: number) => <p className="intake-claim" key={i}>{claim.text}<small>{claim.path}:{claim.line} {tr("· 原文陈述")}</small></p>)}</details>}
    <p className="hint">{tr("本轮新增")}{report.changes.added} {tr("· 变化")}{report.changes.changed} {tr("· 缺失")}{report.changes.missing}{tr("；缺失记录和工作台编辑版本仍保留。")}</p>
    {report.warnings.map((w: string) => <p className="intake-warning" key={w}>{w}</p>)}
    <div className="action-bar"><button className="secondary" disabled={busy || report.restored_snapshot} onClick={rescan}>{busy ? <LoaderCircle size={14} className="spin"/> : <RefreshCw size={14}/>}{tr("重新扫描原项目")}</button><button className="text-button" onClick={() => setPage('documents')}><FileText size={14}/>{tr("查看接入摘要与设计资料")}</button><button className="text-button" onClick={() => setPage('assets')}><Box size={14}/>{tr("查看分类资产")}</button></div>
    <div className="action-bar"><button disabled={busy || appBusy || chatBusy || report.restored_snapshot} onClick={() => setAdding(true)}><FolderOpen size={15}/>{tr("添加来源目录")}</button><button className="secondary" disabled={busy || appBusy || chatBusy || report.restored_snapshot} onClick={onAnalyze}>{tr("让当前 AI 分析与制定整理方案")}</button></div>
    <p className="hint">{tr("AI 分析会向左侧当前选择的服务发送已接入的项目资料，计入该服务用量；本次强制讨论模式，不执行文件改动或收费创作。")}</p>
    <ProjectMaintenance pid={pid} updated={state.updated} run={run} refresh={refresh} busy={appBusy || busy || chatBusy} disabled={report.restored_snapshot}/>
    {adding && <ImportProject project={data.project} projects={[]} close={() => setAdding(false)} finish={async () => { setAdding(false); await refresh(); }} run={run} busy={appBusy}/>}
    <details className="intake-inventory" onToggle={e => setInventoryOpen(e.currentTarget.open)}><summary>{tr("文件目录与分类索引")}</summary><div className="intake-fields"><input aria-label={tr("搜索原项目文件")} value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} placeholder={tr("按相对路径搜索")}/><select aria-label={tr("原项目文件分类")} value={category} onChange={e => { setCategory(e.target.value); setOffset(0); }}><option value="">{tr("全部分类")}</option>{Object.entries(categories).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select></div>
      {files?.items.map((f: any) => <div className="intake-file" key={f.path}><span>{categories[f.category]}</span><code>{f.path}</code><small>{f.status === 'missing' ? tr("原文件缺失") : f.status === 'unseen' ? tr("本次未扫描到") : f.asset_id ? tr("已登记资产") : f.document_id ? tr("已有文档快照") : tr("仅索引")} · {(f.bytes / 1024).toFixed(1)} KB</small></div>)}
      <div className="action-bar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 60))}>{tr("上一页")}</button><small>{files?.total || 0} {tr("项 · 第")}{Math.floor(offset / 60) + 1} {tr("页")}</small><button disabled={!files || offset + 60 >= files.total} onClick={() => setOffset(offset + 60)}>{tr("下一页")}</button></div>
    </details>
    <p className="hint">{tr("可向左侧项目负责人说：“读取原项目接入摘要和设计正文，区分原文陈述、实现线索与已验证成果，继续安排开发。”")}</p>
  </section>;
}
