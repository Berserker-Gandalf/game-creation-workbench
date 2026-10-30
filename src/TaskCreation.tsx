import { t as tr } from './i18n';
import { useEffect, useState } from 'react';
import { api, apiIfChanged, post } from './api';

const kinds: Record<string, string> = { music: tr("SUNO 音乐"), art: tr("美术绘画"), blender: tr("Blender 低模角色"), tripo: tr("Tripo 文生模型") };
const statuses: Record<string, string> = { draft: tr("方案待确认"), submitting: tr("正在提交"), submitted: tr("已提交"), processing: tr("生成中"), building: tr("建模中"), completed: tr("产出已生成"), failed: tr("失败，需核对"), interrupted: tr("已中断，需核对"), unknown: tr("结果未知"), restored: tr("恢复的历史记录"), ready: tr("云端完成，等待接入"), imported: tr("已接入资产"), needs_credits: tr("等待积分处理") };

export default function TaskCreation({ task, close, run, refresh, onError, openJob }: any) {
  const [kind, setKind] = useState('music'), [title, setTitle] = useState(task.title.slice(0, 100));
  const [prompt, setPrompt] = useState(task.detail || ''), [provider, setProvider] = useState('webui');
  const [rows, setRows] = useState<any[]>([]), [busy, setBusy] = useState(false), [ack, setAck] = useState('');
  const load = async () => setRows(await api(`/tasks/${task.id}/creations`));
  useEffect(() => {
    let etag = '';
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => { try { const result = await apiIfChanged(`/tasks/${task.id}/creations`, etag); etag = result.etag; if (active && result.changed) setRows(result.value); } catch (e) { if (active) onError((e as Error).message); } if (active) timer = setTimeout(poll, 2500); };
    poll(); return () => { active = false; clearTimeout(timer); };
  }, [task.id]);
  const create = () => run(async () => {
    setBusy(true);
    try {
      const data = kind === 'art' ? { provider, prompt, width: 512, height: 512 } : kind === 'blender' ? { title, brief: prompt } : { title, prompt, ...(kind === 'music' ? { instrumental: true } : { mode: 'text' }) };
      await post(`/tasks/${task.id}/creations`, { kind, data }); await load(); await refresh();
    } finally { setBusy(false); }
  }, tr("方案已与任务关联，尚未提交生成；可查看原作业继续处理"));
  return <div className="modal-overlay"><section className="modal task-modal" role="dialog" aria-modal="true" aria-label={tr("任务创作与候选交付")}><div className="modal-heading"><h2>{task.title} {tr("· 创作与交付")}</h2><button onClick={close}>{tr("关闭创作面板")}</button></div>
    <p>{tr("保存免费方案，生成和服务费用在原作业中明确确认。产出自动出现在这里，采用版本后仍需独立验收。")}</p>
    <label>{tr("创作类型")}<select aria-label={tr("任务创作类型")} value={kind} onChange={e => setKind(e.target.value)}>{Object.entries(kinds).map(([k, text]) => <option key={k} value={k}>{text}</option>)}</select></label>
    {kind !== 'art' && <label>{tr("方案名称")}<input aria-label={tr("任务方案名称")} value={title} maxLength={100} onChange={e => setTitle(e.target.value)}/></label>}
    {kind === 'art' && <label>{tr("绘画来源")}<select aria-label={tr("任务绘画来源")} value={provider} onChange={e => setProvider(e.target.value)}><option value="webui">{tr("本机 WebUI")}</option><option value="openai">{tr("OpenAI 图像 API")}</option></select></label>}
    <label>{kind === 'blender' ? tr("角色设计说明（使用现有参数模板，可到建模页派生调整）") : tr("创作需求")}<textarea aria-label={tr("任务创作需求")} value={prompt} maxLength={kind === 'tripo' ? 1024 : kind === 'blender' ? 2000 : 8000} onChange={e => setPrompt(e.target.value)}/></label>
    <button className="primary" disabled={busy || !prompt.trim() || kind !== 'art' && !title.trim() || ['done', 'cancelled'].includes(task.status)} onClick={create}>{tr("保存方案并关联此任务（不生成）")}</button>
    {['done', 'cancelled'].includes(task.status) && <p className="intake-warning">{tr("当前任务已结束。先在任务看板重新安排为待执行，再创建新方案。")}</p>}
    <h3>{tr("已有方案与候选产出")}</h3>{!rows.length && <p>{tr("尚无关联方案。")}</p>}{rows.map(row => <div className="acceptance-receipt" key={row.id}><p>{kinds[row.kind]} · {row.title} · {statuses[row.status] || tr("待核对")}</p><button onClick={() => openJob({ kind: row.kind, id: row.job_id })}>{tr("查看原作业与处理入口")}</button>{row.outputs.map((o: any) => <div className="job-output" key={o.asset_id}><strong>{o.name}</strong>{o.kind === 'image' && <img className="task-candidate-image" alt={tr("任务候选：") + o.name} src={`/api/assets/${o.asset_id}/file`}/>}<label className="check-row"><input type="checkbox" aria-label={tr("确认采用候选 ") + o.name} checked={ack === o.asset_id} onChange={e => setAck(e.target.checked ? o.asset_id : '')}/>{tr("采用当前版本并将任务重新安排为待执行")}</label><button disabled={busy || ack !== o.asset_id} onClick={() => run(async () => { await post(`/tasks/${task.id}/creations/adopt`, { asset_id: o.asset_id, confirmed: true }); setAck(''); await refresh(); }, tr("已采用候选当前版本，任务待执行；尚未验收"))}>{tr("采用此候选版本")}</button></div>)}</div>)}
  </section></div>;
}
