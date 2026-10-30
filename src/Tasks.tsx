import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { CheckCircle2, Plus, X } from 'lucide-react';
import { api, patch, post } from './api';
import TaskCreation from './TaskCreation';
import { CatalogChecks, CatalogPages, useCatalog } from './Catalog';

const states: Record<string, string> = { todo: tr("待执行"), running: tr("进行中"), review: tr("待验收"), done: tr("已完成"), blocked: tr("受阻"), cancelled: tr("已取消") };

export default function Tasks({ data: projectData, run, refresh: refreshProject, onError, openJob, setPage }: any) {
  const [query, setQuery] = useState(''), [tick, setTick] = useState(0);
  const listing = useCatalog(projectData.project.id, 'task-board', query, '', '', projectData.as_of + tick);
  const data = { ...projectData, tasks: listing.items };
  const refresh = async () => { await refreshProject(); setTick(v => v + 1); };
  const [title, setTitle] = useState(''), [detail, setDetail] = useState('');
  const [editing, setEditing] = useState<any>(null);
  const [accepting, setAccepting] = useState<any>(null), [evidence, setEvidence] = useState('');
  const [creation, setCreation] = useState<any>(null);
  const [history, setHistory] = useState<any>(null);
  useEffect(() => {
    if (listing.loading) return;
    const timer = setTimeout(() => setTick(v => v + 1), 2500);
    return () => clearTimeout(timer);
  }, [data.project.id, listing.loading, tick]);
  const change = (task: any, status: string) => run(async () => {
    let evidence = task.evidence;
    if (status === 'done') {
      const current = await api(`/tasks/${task.id}`);
      if (!current) throw new Error(tr("任务已变化，请刷新后重新选择"));
      setAccepting(current); setEvidence(''); return;
    }
    await patch(`/tasks/${task.id}`, { status, evidence }); await refresh();
  });
  const card = (task: any) => <div className="task-card" key={task.id}>
    <h4>{task.title}</h4>{task.detail && <p>{task.detail}</p>}
    {task.issues.length > 0 && <div className="task-issues">{task.issues.map((issue: string, i: number) => <p key={i}>{serverText(issue)}</p>)}</div>}
    {task.evidence && <div className="evidence"><CheckCircle2 size={13}/>{task.evidence}</div>}
    {task.asset_links.map((v: any) => <p className="task-delivery" key={v.asset_id}>{v.name} · v{v.version_index + 1}{v.changed ? tr(" · 需复核") : tr(" · 已固定版本")}<small>SHA-256 {v.sha256}{v.origin && tr(" · 来源 {0} / {1}", v.origin.kind, v.origin.model || tr("模型未记录"))}</small></p>)}
    <select aria-label={tr("任务状态：") + task.title} value={task.status} onChange={e => change(task, e.target.value)}>
      {Object.entries(states).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
    </select>
    <button className="text-button task-links-button" onClick={() => setEditing(task)}>{tr("编辑与关联 ·")}{task.dependency_ids.length} {tr("个依赖 /")}{task.document_links.length} {tr("份设计 /")}{task.asset_links.length} {tr("份资产")}</button>
    <button className="text-button" onClick={() => setCreation(task)}>{tr("创作方案与候选交付")}</button>
    {task.asset_links.some((v: any) => v.missing) && <button className="text-button" onClick={() => setPage('assets')}>{tr("前往资产区核对缺失文件")}</button>}
    <button className="text-button" onClick={() => run(async () => setHistory({ task, values: await api(`/tasks/${task.id}/acceptances`) }))}>{tr("查看验收快照")}</button>
  </div>;
  return <div className="page-content">
    <div className="card task-create">
      <input aria-label={tr("任务标题")} placeholder={tr("添加一个可验收的任务…")} value={title} onChange={e => setTitle(e.target.value)}/>
      <input aria-label={tr("任务验收条件")} placeholder={tr("交付物与验收条件（可选）")} value={detail} onChange={e => setDetail(e.target.value)}/>
      <button className="primary" disabled={!title.trim()} onClick={() => run(async () => { await post(`/projects/${data.project.id}/tasks`, { title, detail }); setTitle(''); setDetail(''); await refresh(); })}><Plus size={15}/>{tr("添加任务")}</button>
    </div>
    <p className="hint">{listing.loading ? tr("正在完整核对依赖与交付文件…") : tr("全项目有效完成 {0} / {1} 项；下方仅展示本页任务。", listing.accepted_tasks || 0, listing.total_tasks || 0)}{tr("前置任务完成后才能执行或验收；关联设计更新后，需复核再采用。过期验收不计入当前进度。")}</p>
    <input aria-label={tr("搜索任务看板")} placeholder={tr("搜索全部任务标题")} value={query} onChange={e => setQuery(e.target.value)}/><CatalogPages catalog={listing}/>
    <div className="kanban">{['todo', 'running', 'review', 'done'].map(state => <div className="kanban-column" key={state}>
      <h3><span className={'status-dot ' + state}/>{states[state]}<small>{data.tasks.filter((t: any) => t.status === state).length}</small></h3>
      {data.tasks.filter((t: any) => t.status === state).map(card)}
    </div>)}</div>
    {data.tasks.some((t: any) => ['blocked', 'cancelled'].includes(t.status)) && <div className="inactive-tasks"><h3>{tr("受阻与取消")}</h3>{data.tasks.filter((t: any) => ['blocked', 'cancelled'].includes(t.status)).map(card)}</div>}
    {creation && <TaskCreation task={data.tasks.find((t: any) => t.id === creation.id) || creation} close={() => setCreation(null)} run={run} refresh={refresh} onError={onError} openJob={(target: any) => { setCreation(null); openJob(target); }}/>}
    {editing && <TaskEditor key={editing.id} task={editing} data={data} run={run} refresh={refresh} close={() => setEditing(null)}/>}
    {accepting && <div className="modal-overlay"><section className="modal task-modal" role="dialog" aria-modal="true" aria-label={tr("记录任务验收")}><div className="modal-heading"><h2>{tr("验收：")}{accepting.title}</h2><button onClick={() => setAccepting(null)}>{tr("取消验收")}</button></div><p>{tr("核对具体资产版本与设计依据，再记录验收证据。文件已生成或已下载不代表质量、引擎运行或授权已验收。")}</p>{accepting.asset_links.map((v: any) => <p className="task-delivery" key={v.asset_id}>{v.name} · v{v.version_index + 1}<small>SHA-256 {v.sha256}</small></p>)}<label>{tr("验收依据")}<textarea aria-label={tr("任务验收证据")} value={evidence} maxLength={10000} onChange={e => setEvidence(e.target.value)} placeholder={tr("试听/检查的内容、文件版本、测试结果和范围…")}/></label>{!accepting.ready && <p className="intake-warning">{tr("依据或前置交付已过期，请先复核并重新安排任务。")}</p>}<button className="primary" disabled={!accepting.ready || !evidence.trim()} onClick={() => run(async () => { await patch(`/tasks/${accepting.id}`, { status: 'done', evidence, review_token: accepting.review_token }); setAccepting(null); await refresh(); }, tr("已保存本次验收证据与版本快照"))}>{tr("记录验收并标记完成")}</button></section></div>}
    {history && <div className="modal-overlay"><section className="modal task-modal" role="dialog" aria-modal="true" aria-label={tr("任务验收历史")}><div className="modal-heading"><h2>{history.task.title} {tr("· 验收快照")}</h2><button onClick={() => setHistory(null)}>{tr("关闭验收历史")}</button></div>{!history.values.length && <p>{tr("尚无结构化验收记录；旧任务的文字依据仍保留。")}</p>}{history.values.map((v: any) => <div className="acceptance-receipt" key={v.id}><p>{new Date(v.created).toLocaleString(dateLocale)} · {v.evidence}</p>{v.snapshot.deliveries.map((a: any) => <p className="task-delivery" key={a.asset_id}>{a.name || data.assets.find((x: any) => x.id === a.asset_id)?.name || tr("历史资产")} · v{a.version_index + 1}<small>SHA-256 {a.sha256}{a.origin && tr(" · 来源模型 {0}", a.origin.model || tr("未记录"))}</small></p>)}<details><summary>{tr("当时的设计、资产版本与生成依据")}</summary><pre>{JSON.stringify(v.snapshot, null, 2)}</pre></details></div>)}</section></div>}
  </div>;
}

function TaskEditor({ task, data, run, refresh, close }: any) {
  const [title, setTitle] = useState(task.title), [detail, setDetail] = useState(task.detail);
  const [dependencies, setDependencies] = useState<string[]>(task.dependency_ids);
  const originalDocs: string[] = task.document_links.map((l: any) => l.doc_id);
  const [documents, setDocuments] = useState<string[]>(originalDocs);
  const [saving, setSaving] = useState(false);
  const originalPins = task.asset_links.map((v: any) => ({ asset_id: v.asset_id, version_index: v.version_index, sha256: v.sha256 }));
  const [pins, setPins] = useState<any[]>(originalPins), [loadingAsset, setLoadingAsset] = useState(false);
  const pinChanged = JSON.stringify(pins) !== JSON.stringify(originalPins);
  const toggleAsset = (asset: any) => run(async () => {
    if (pins.some(v => v.asset_id === asset.id)) { setPins(pins.filter(v => v.asset_id !== asset.id)); return; }
    setLoadingAsset(true);
    try { const info = await api(`/assets/${asset.id}/info`); setPins(old => [...old, { asset_id: asset.id, version_index: info.version_index, sha256: info.hash }]); }
    finally { setLoadingAsset(false); }
  });
  const toggle = (ids: string[], id: string) => ids.includes(id) ? ids.filter(v => v !== id) : [...ids, id];
  const save = async (acknowledge = false) => {
    setSaving(true);
    try {
      const result = await run(async () => {
        const body: any = { title, detail, dependency_ids: dependencies };
        if (acknowledge || JSON.stringify([...documents].sort()) !== JSON.stringify([...originalDocs].sort())) body.document_ids = documents;
        if (acknowledge || pinChanged) body.deliveries = pins.map(v => {
          const previous = task.asset_links.find((p: any) => p.asset_id === v.asset_id);
          if (acknowledge && previous?.changed && previous.version_index === v.version_index && previous.sha256 === v.sha256) {
            if (previous.current_version_index === null || !previous.current_hash) throw new Error(tr("交付文件缺失，请先恢复或重新选择"));
            return { asset_id: v.asset_id, version_index: previous.current_version_index, sha256: previous.current_hash };
          }
          return v;
        });
        if (acknowledge) body.status = 'todo';
        const updated = await patch(`/tasks/${task.id}`, body);
        await refresh(); return updated;
      }, acknowledge ? tr("已采用当前设计，任务重新安排为待执行；请重新交付和验收") : tr("任务关联已保存"));
      if (result) close();
    } finally { setSaving(false); }
  };
  return <div className="modal-overlay"><section className="modal task-modal" role="dialog" aria-modal="true" aria-label={tr("任务关联")}>
    <div className="modal-heading"><h2>{tr("任务与设计依据")}</h2><button aria-label={tr("关闭任务编辑")} className="icon-button" onClick={close}><X size={20}/></button></div>
    <label>{tr("任务名称")}<input aria-label={tr("编辑任务名称")} value={title} onChange={e => setTitle(e.target.value)}/></label>
    <label>{tr("交付与验收条件")}<textarea aria-label={tr("编辑任务验收条件")} value={detail} onChange={e => setDetail(e.target.value)}/></label>
    <fieldset><legend>{tr("前置任务")}</legend><CatalogChecks pid={data.project.id} section="tasks" exclude={task.id} selected={dependencies} pinned={dependencies.map(id => data.tasks.find((v: any) => v.id === id) || { id })} change={(v: any) => { if (v.id !== task.id) setDependencies(toggle(dependencies, v.id)); }} disabled={saving}/><p className="hint">{tr("不能依赖自身或形成循环；保存时服务端完整核对。")}</p></fieldset>
    <fieldset><legend>{tr("设计依据")}</legend>{task.document_links.map((v: any) => <p key={v.doc_id}>{v.title} {tr("· 采用v")}{v.revision} {tr("/ 当前v")}{v.current_revision}{v.changed ? tr(" · 需复核") : ''}</p>)}<CatalogChecks pid={data.project.id} section="documents" selected={documents} pinned={task.document_links.map((v: any) => ({ id: v.doc_id, title: v.title }))} change={(v: any) => setDocuments(toggle(documents, v.id))} disabled={saving}/></fieldset>
    <fieldset><legend>{tr("资产交付 · 固定版本与SHA-256")}</legend>{pins.map(v => <p className="task-delivery" key={v.asset_id}>{task.asset_links.find((x: any) => x.asset_id === v.asset_id)?.name || v.asset_id} · v{v.version_index + 1}<small>SHA-256 {v.sha256}</small></p>)}{task.asset_links.filter((v: any) => v.changed).map((v: any) => <p className="intake-warning" key={v.asset_id}>{v.name} {tr("· 当前v")}{v.current_version_index === null ? tr("缺失") : v.current_version_index + 1} / {v.current_hash || tr("不可读取")}</p>)}<CatalogChecks pid={data.project.id} section="assets" selected={pins.map(v => v.asset_id)} pinned={task.asset_links.map((v: any) => ({ id: v.asset_id, name: v.name }))} change={toggleAsset} disabled={saving || loadingAsset}/></fieldset>
    <p className="hint">{tr("仅调整标题或依赖不会自动接受新版设计。新增设计关联采用该文档的当前版本。")}</p>
    {(task.review_required || pinChanged || task.asset_links.some((v: any) => v.changed) || task.document_links.some((l: any) => l.changed)) && <button className="secondary full-width" disabled={saving || loadingAsset} onClick={() => save(true)}>{tr("确认采用已显示的当前设计与交付，重置为待执行")}</button>}
    <button className="primary full-width" disabled={saving || loadingAsset || !title.trim()} onClick={() => save()}>{tr("保存任务与关联")}</button>
  </section></div>;
}
