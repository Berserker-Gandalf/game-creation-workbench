import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useRef, useState } from 'react';
import { api, apiIfChanged, patch, post } from './api';
import { CatalogPages, useCatalog } from './Catalog';

const types: Record<string, string> = { music: tr("SUNO音乐"), art: tr("绘画"), blender: tr("Blender建模"), tripo: tr("Tripo建模"), snapshot: tr("工程快照"), publication: tr("GitHub发布"), chat: tr("AI对话"), operation: tr("查询 / 下载队列") };
const states: Record<string, string> = { queued: tr("排队中"), running: tr("进行中"), succeeded: tr("作业成功"), failed: tr("失败"), unknown: tr("结果未知"), needs_user: tr("等待处理"), cancelled: tr("本机操作已取消"), interrupted: tr("已中断") };
const sourceStates: Record<string, string> = { completed: tr("生成完成，文件与验收另行核对"), processing: tr("仍在生成"), ready: tr("云端完成，等待接入"), imported: tr("资产已接入"), submitted: tr("已提交"), queued: tr("排队中"), running: tr("仍在运行"), failed: tr("业务失败"), unknown: tr("结果未知"), restored: tr("历史记录") };

export default function Jobs({ data, run, busy, refresh, onError, setPage, initialJob }: any) {
  const pid = data.project.id;
  const [kind, setKind] = useState(''), [state, setState] = useState(''), [query, setQuery] = useState(''), [offset, setOffset] = useState(0);
  const [listing, setListing] = useState<any>(null), [selected, setSelected] = useState<any>(initialJob || null), [detail, setDetail] = useState<any>(null);
  const [serial, setSerial] = useState(''), [ack, setAck] = useState(false), [taskId, setTaskId] = useState('');
  const [taskQuery, setTaskQuery] = useState('');
  const taskCatalog = useCatalog(pid, 'tasks', taskQuery);
  const signature = useRef('');
  useEffect(() => { if (initialJob) setSelected(initialJob); }, [initialJob?.kind, initialJob?.id]);
  const listUrl = `/projects/${pid}/jobs?kind=${kind}&state=${state}&q=${encodeURIComponent(query)}&offset=${offset}`;
  useEffect(() => {
    let etag = '';
    let active = true, timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try { const response = await apiIfChanged(listUrl, etag); etag = response.etag; const value = response.value; if (active && response.changed) { setListing(value); const next = JSON.stringify(value.items); if (signature.current !== next) { signature.current = next; await refresh(); } } }
      catch (e) { if (active) onError((e as Error).message); }
      if (active) timer = setTimeout(load, 2500);
    };
    load(); return () => { active = false; clearTimeout(timer); };
  }, [pid, kind, state, query, offset]);
  useEffect(() => {
    setAck(false); setDetail(null); if (!selected) return;
    let etag = '';
    let active = true, timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try { const response = await apiIfChanged(`/projects/${pid}/jobs/inspect?kind=${selected.kind}&id=${encodeURIComponent(selected.id)}`, etag); etag = response.etag; const value = response.value; if (active && response.changed) { setDetail(value); const ids = value.import_serials || []; setSerial(old => ids.includes(old) ? old : ids[0] || ''); } }
      catch (e) { if (active) onError((e as Error).message); }
      if (active) timer = setTimeout(load, 2500);
    };
    load(); return () => { active = false; clearTimeout(timer); };
  }, [pid, selected?.kind, selected?.id]);
  const enqueue = (command: string) => run(async () => {
    const result = await post(`/projects/${pid}/jobs/commands`, { kind: selected.kind, id: selected.id, command, ...(command === 'import' ? { confirmed: ack, ...(selected.kind === 'music' ? { serial_no: serial } : {}) } : {}) });
    setSelected({ kind: 'operation', id: result.id }); setAck(false); setListing(await api(listUrl)); await refresh();
  }, tr("操作已排队；可查看此查询/下载作业，不会重新提交生成"));
  const attach = (aid: string) => run(async () => {
    if (!taskId) throw new Error(tr("请先选择要关联的任务"));
    const task = await api(`/tasks/${taskId}`);
    if (task.project_id !== pid) throw new Error(tr("任务不属于当前项目"));
    const info = await api(`/assets/${aid}/info`);
    const pins = task.asset_links.filter((v: any) => v.asset_id !== aid).map((v: any) => ({ asset_id: v.asset_id, version_index: v.version_index, sha256: v.sha256 }));
    await patch(`/tasks/${task.id}`, { status: 'todo', deliveries: [...pins, { asset_id: aid, version_index: info.version_index, sha256: info.hash }] });
    await refresh();
  }, tr("已关联当前资产版本，任务重置为待执行；仍需试听/检查与重新验收"));
  return <div className="page-content jobs-page">
    <section className="card jobs-intro"><h2>{tr("把生成、文件交付和验收分开管理。")}</h2><p>{tr("每2.5秒检查本机变化，增量更新任务和资产。云端状态需点击接续查询；收费提交不自动重放。下载和查询独立排队，保留重启后的状态。")}</p><button onClick={() => setPage('tasks')}>{tr("查看任务与交付验收")}</button></section>
    <div className="jobs-filters"><select aria-label={tr("作业类型")} value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}><option value="">{tr("全部类型")}</option>{Object.entries(types).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label={tr("作业状态")} value={state} onChange={e => { setState(e.target.value); setOffset(0); }}><option value="">{tr("全部状态")}</option>{Object.entries(states).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><input aria-label={tr("搜索作业")} placeholder={tr("搜索作业名称")} value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }}/></div>
    <p className="hint">{tr("成功表示对应操作结束；生成、文件接入及任务验收各有独立记录。恢复副本中的队列只作历史，不自动执行。")}</p>
    <div className="jobs-list">{listing?.items.map((job: any) => <button className={'card jobs-row ' + (selected?.kind === job.kind && selected?.id === job.id ? 'selected' : '')} key={job.kind + job.id} onClick={() => setSelected({ kind: job.kind, id: job.id })}><span><small>{types[job.kind]}</small><strong>{job.title}</strong></span><span><b>{states[job.state] || tr("待核对")}</b><small>{new Date(job.updated).toLocaleString(dateLocale)}</small></span></button>)}</div>
    <div className="action-bar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>{tr("上一页")}</button><small>{listing?.total || 0} {tr("项 · 第")}{Math.floor(offset / 30) + 1} {tr("页")}</small><button disabled={!listing || offset + 30 >= listing.total} onClick={() => setOffset(offset + 30)}>{tr("下一页")}</button></div>
    {detail && <section className="card jobs-detail"><div className="section-heading"><h2>{types[detail.kind]} · {detail.title}</h2><button onClick={() => setSelected(null)}>{tr("关闭详情")}</button></div><p>{serverText(detail.note)}</p>
      {detail.details.error && <p className="intake-warning">{detail.details.error}</p>}
      {detail.kind === 'operation' && <><p>{tr("本次")}{detail.details.action === 'query' ? tr("查询") : tr("文件接入")}{tr("状态：")}{states[detail.details.status] || tr("待核对")}</p>{detail.details.result?.source_status && <p>{tr("原业务状态：")}{sourceStates[detail.details.result.source_status] || tr("请查看原记录")}{detail.details.result.asset_id && tr("；本次已登记资产，仍需任务验收")}</p>}<button onClick={() => setSelected({ kind: detail.details.source_kind, id: detail.details.source_id })}>{tr("查看原业务作业并手动接续")}</button></>}
      {['unknown', 'interrupted', 'failed', 'needs_credits', 'needs_user', 'restored', 'draft'].includes(detail.details.status) && <p className={detail.details.status === 'draft' ? 'hint' : 'intake-warning'}>{detail.details.status === 'unknown' || detail.details.status === 'interrupted' ? tr("先核对原服务记录，不自动重新提交生成。") : detail.details.status === 'draft' ? tr("方案尚未执行，请核对参数后明确提交。") : tr("请核对连接、方案与原业务状态。")}<button onClick={() => setPage((detail.details.source_kind || detail.kind) === 'music' ? 'music' : ['tripo', 'blender'].includes(detail.details.source_kind || detail.kind) ? 'blender' : ['publication', 'snapshot'].includes(detail.kind) ? 'management' : detail.kind === 'art' && detail.details.provider === 'webui' ? 'webui' : 'connections')}>{tr("打开对应工作区处理")}</button></p>}
      {detail.actions.includes('generate') && <div className="job-import-confirm"><p>{tr("核对下方美术方案。WebUI实际模型在执行时解析并记录；OpenAI沿用草稿中已记录的模型，未配置时需先配置。")}</p><label className="check-row"><input type="checkbox" aria-label={tr("确认执行美术方案")} checked={ack} onChange={e => setAck(e.target.checked)}/>{tr("确认执行此方案，并接受所选图像服务可能产生的费用；仅提交一次")}</label><button disabled={busy || !ack} onClick={() => run(async () => { await post(`/art-jobs/${detail.id}/generate`, { confirmed: true }); setAck(false); await refresh(); setDetail(await api(`/projects/${pid}/jobs/inspect?kind=art&id=${detail.id}`)); }, tr("美术请求结束；请核对产出，再到原任务采用版本和验收"))}>{tr("执行已确认的美术方案")}</button></div>}
      {detail.details.origin_task_id && <button onClick={() => setPage('tasks')}>{tr("返回原任务查看候选交付")}</button>}
      <div className="action-bar">{detail.actions.includes('query') && <button disabled={busy} onClick={() => enqueue('query')}>{tr("接续查询已有任务（不重新生成）")}</button>}{detail.actions.includes('stop') && <button disabled={busy} onClick={() => run(async () => { await post(`/projects/${pid}/jobs/stop`, selected); await refresh(); }, tr("已请求停止本机操作；云端生成及已有文件不自动撤销"))}>{tr("停止支持的本机操作")}</button>}</div>
      {detail.actions.includes('import') && <div className="job-import-confirm">{detail.kind === 'music' && <label>{tr("要接入的音轨")}<select aria-label={tr("接入音轨")} value={serial} onChange={e => { setSerial(e.target.value); setAck(false); }}>{detail.import_serials.map((s: string) => <option key={s}>{s}</option>)}</select></label>}<label className="check-row"><input type="checkbox" aria-label={tr("确认下载已有产出")} checked={ack} disabled={busy} onChange={e => setAck(e.target.checked)}/>{tr("确认下载此已有产出到当前项目；不提交生成或收费转换")}</label><button disabled={busy || !ack} onClick={() => enqueue('import')}>{tr("排队下载并校验纳入资产")}</button></div>}
      {!!detail.outputs.length && <><h3>{tr("已登记产出与任务交付")}</h3><input aria-label={tr("搜索交付关联任务")} placeholder={tr("搜索全部任务")} value={taskQuery} onChange={e => setTaskQuery(e.target.value)}/><CatalogPages catalog={taskCatalog}/><select disabled={taskCatalog.loading} aria-label={tr("交付关联任务")} value={taskId} onChange={e => setTaskId(e.target.value)}><option value="">{tr("选择任务")}</option>{taskId && !taskCatalog.items.some((t: any) => t.id === taskId) && <option value={taskId}>{tr("已选任务：")}{taskId}</option>}{taskCatalog.items.map((t: any) => <option key={t.id} value={t.id}>{t.title}</option>)}</select>{detail.outputs.map((output: any) => <div className="job-output" key={output.asset_id}><strong>{output.name}</strong><small>{tr("核对当前资产版本；关联任务时重新读取版本与哈希。")}</small>{output.mime?.startsWith('audio/') && <audio controls preload="none" src={`/api/assets/${output.asset_id}/file`}/>}<small>{output.sha256 && tr("原始接入 SHA-256 {0}", output.sha256)}</small><button disabled={busy || !taskId} onClick={() => attach(output.asset_id)}>{tr("关联此资产当前版本，并重置任务为待执行")}</button></div>)}</>}
      <details><summary>{tr("参数、原始状态与执行依据")}</summary><pre>{JSON.stringify(detail.details, null, 2)}</pre></details>
    </section>}
  </div>;
}
