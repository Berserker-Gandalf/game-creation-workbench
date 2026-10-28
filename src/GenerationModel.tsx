import { serverText } from './i18n';
import { t as tr } from './i18n';
import { useEffect, useState } from 'react';
import { api } from './api';

export default function GenerationModel({ pid, service, run, busy, onSaved }: any) {
  const [catalog, setCatalog] = useState<any>(null), [value, setValue] = useState('');
  useEffect(() => { let active = true; run(async () => { const c = await api(`/projects/${pid}/generation-models`); if (active) { setCatalog(c); setValue(c.selected[service]); } }); return () => { active = false; }; }, [pid, service]);
  return <section className="card generation-model"><label>{service === 'suno' ? tr("SUNO 音乐模型") : tr("Tripo 项目默认模型")}<select aria-label={service === 'suno' ? tr("SUNO 生成模型") : tr("Tripo 项目默认模型")} value={value} disabled={busy || !catalog} onChange={e => setValue(e.target.value)}>{catalog?.[service].map((m: any) => <option value={m.id} key={m.id}>{serverText(m.label)}</option>)}</select></label><button className="secondary" disabled={busy || !catalog} onClick={() => run(async () => { const c = await api(`/projects/${pid}/generation-models`, { method: 'PUT', body: JSON.stringify({ [service]: value }) }); setCatalog(c); onSaved?.(c.selected[service]); }, tr("项目默认生成模型已保存；已有方案保持原模型"))}>{tr("保存项目默认模型")}</button><small>{serverText(catalog?.source[service])}{tr("。影响 Agent 和新方案；已有方案按已记录模型执行，积分以服务计费为准。")}</small></section>;
}
