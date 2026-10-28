import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { api, post } from './api';

const statusText: Record<string, string> = { completed: tr("归档完成"), partial: tr("部分完成"), failed: tr("失败"), interrupted: tr("已中断"), running: tr("进行中") };
const size = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GiB` : `${(bytes / 1024 ** 2).toFixed(2)} MiB`;

export default function ProjectMaintenance({ pid, updated, run, refresh, busy, disabled }: any) {
  const [opened, setOpened] = useState(false);
  const [data, setData] = useState<any>(null), [selected, setSelected] = useState<string[]>([]), [ack, setAck] = useState(false);
  const [files, setFiles] = useState<any>(null);
  const [restoreId, setRestoreId] = useState(''), [restoreAck, setRestoreAck] = useState(false);
  const load = () => api(`/projects/${pid}/maintenance`).then(setData);
  useEffect(() => { if (opened) load().catch(e => run(async () => { throw e; })); }, [pid, updated, opened]);
  const audit = data?.audit;
  useEffect(() => { setSelected([]); setAck(false); setFiles(null); }, [audit?.id]);
  const readFiles = (candidate: string, offset = 0) => run(async () => setFiles(await api(`/projects/${pid}/maintenance/files?audit_id=${encodeURIComponent(audit.id)}&candidate_id=${encodeURIComponent(candidate)}&offset=${offset}`)));
  const scan = () => run(async () => { await post(`/projects/${pid}/maintenance/audit`); setSelected([]); setAck(false); await load(); await refresh(); });
  const archive = () => run(async () => {
    const result = await post(`/projects/${pid}/maintenance/archive`, { audit_id: audit.id, candidate_ids: selected, editor_closed_ack: ack, confirmed: true });
    setSelected([]); setAck(false); await load(); await refresh();
    if (result.status !== 'completed') throw new Error(tr("归档未完全完成：{0}。请查看记录与备份，勿直接重复执行。", result.error || result.status));
  });
  return <details className="project-maintenance" onToggle={e => setOpened(e.currentTarget.open)}><summary>{tr("项目整理与可恢复瘦身")}</summary>
    <p className="hint">{tr("规则审计负责体积、分类和重复样本，AI 负责结合设计解释与建议。不会自动移动原生资产或删除“疑似无用”文件。仅已识别主工程的少数可重建缓存允许确认后归档。")}</p>
    <button disabled={busy || disabled} onClick={scan}>{tr("扫描空间与重复样本")}</button>
    {audit && <>
      <p>{new Date(audit.created).toLocaleString(dateLocale)} {tr("· 已扫描")}{audit.file_count} {tr("个文件 /")}{size(audit.bytes)}</p>
      <p className="hint">{serverText(audit.note)}</p>
      {audit.warnings.map((w: string) => <p className="intake-warning" key={w}>{w}</p>)}
      <div className="intake-counts">{Object.entries(audit.categories).map(([key, bytes]: any) => <span key={key}>{({ cache: tr("可重建缓存"), design: tr("设计资料"), code: tr("代码"), image: tr("图片"), model: tr("模型"), audio: tr("音频"), config: tr("工程配置"), scene: tr("关卡 / 场景"), prefab: tr("预制体"), material: tr("材质"), animation: tr("动画"), native: tr("原生资产"), other: tr("其他文件") } as any)[key] || key}<strong>{size(bytes)}</strong></span>)}</div>
      <details><summary>{tr("体积较大的文件")}</summary>{audit.largest_files.map((f: any) => <p key={f.path}><code>{f.path}</code><small>{size(f.bytes)} · {f.category}</small></p>)}</details>
      <details><summary>{tr("重复内容样本 · 仅建议核对")}</summary>{!audit.duplicates.length ? <p className="hint">{tr("受限样本中未发现重复；不代表全工程没有重复。")}</p> : audit.duplicates.map((g: any) => <div key={g.sha256}><p>{g.count} {tr("份 · 每份")}{size(g.bytes_each)}</p>{g.paths.map((path: string) => <p key={path}><code>{path}</code></p>)}<small>{g.action}</small></div>)}</details>
      <h3>{tr("可恢复缓存归档")}</h3>
      {!audit.candidates.length && <p className="hint">{tr("没有找到支持自动归档的缓存。Saved、Binaries、源码、.meta、Git 历史和游戏资产不在移除范围。")}</p>}
      {audit.candidates.map((c: any) => <div key={c.id}><label className="maintenance-candidate"><input type="checkbox" aria-label={tr("归档缓存 ") + c.path} disabled={busy || disabled || !c.eligible} checked={selected.includes(c.id)} onChange={e => { setSelected(old => e.target.checked ? [...old, c.id] : old.filter(k => k !== c.id)); setAck(false); }}/><span><strong>{c.path} · {size(c.bytes)} / {c.file_count} {tr("文件")}</strong><small>{c.reason}</small></span></label><button disabled={busy} onClick={() => readFiles(c.id)}>{tr("查看")}{c.path} {tr("文件清单")}</button></div>)}
      {files && <div><h3>{files.candidate_id} {tr("文件清单")}</h3>{files.items.map((f: any) => <p key={f.relative_path}><code>{f.relative_path}</code><small>{size(f.bytes)}</small></p>)}<div className="action-bar"><button disabled={busy || !files.offset} onClick={() => readFiles(files.candidate_id, Math.max(0, files.offset - 30))}>{tr("上一页")}</button><small>{files.total} {tr("项 · 第")}{Math.floor(files.offset / 30) + 1} {tr("页")}</small><button disabled={busy || files.offset + 30 >= files.total} onClick={() => readFiles(files.candidate_id, files.offset + 30)}>{tr("下一页")}</button></div></div>}
      {!!selected.length && <><label><input type="checkbox" aria-label={tr("确认编辑器关闭与缓存归档")} checked={ack} disabled={busy || disabled} onChange={e => setAck(e.target.checked)}/>{tr("我已关闭编辑器并暂停写入，已审阅所选缓存，同意保留校验备份后移除原文件")}</label><button disabled={busy || disabled || !ack} onClick={archive}>{tr("归档所选缓存并移出原文件")}</button></>}
    </>}
    {!!data?.history.length && <><h3>{tr("归档与恢复记录")}</h3>{data.history.map((job: any) => { const recovery = JSON.parse(job.runtime || '{}'); return <div className="maintenance-history" key={job.id}><p>{new Date(job.created).toLocaleString(dateLocale)} · {statusText[job.status] || tr("待核对")}</p><small>{job.detail}</small>{recovery.status && <p>{tr("上次恢复：")}{recovery.restored_files} {tr("个文件 · 冲突或写入失败")}{recovery.conflicts?.length || 0} {tr("项")}</p>}<button disabled={busy || disabled} onClick={() => { setRestoreId(job.id); setRestoreAck(false); }}>{tr("准备恢复缺失文件")}</button>{restoreId === job.id && <><label className="maintenance-candidate"><input type="checkbox" aria-label={tr("确认关闭编辑器并恢复缓存")} checked={restoreAck} disabled={busy} onChange={e => setRestoreAck(e.target.checked)}/>{tr("我已关闭编辑器并暂停写入；仅补回缺失文件，已有不同内容不覆盖，校验备份继续保留")}</label><button disabled={busy || disabled || !restoreAck} onClick={() => run(async () => {
      const result = await post(`/projects/${pid}/maintenance/${job.id}/restore`, { confirmed: true, editor_closed_ack: true });
      setRestoreId(''); setRestoreAck(false);
      await load(); await refresh();
      if (result.conflicts.length) throw new Error(tr("已恢复 {0} 个文件；{1} 个冲突或写入失败未覆盖：{2}", result.restored_files, result.conflicts.length, result.conflicts.slice(0, 5).join('、')));
    })}>{tr("确认恢复归档中的缺失文件")}</button><button disabled={busy} onClick={() => setRestoreId('')}>{tr("取消恢复")}</button></>}</div>; })}</>}
  </details>;
}
