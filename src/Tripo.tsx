import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import React, { useEffect, useRef, useState } from 'react';
import { Box, Copy, Download, ExternalLink, RefreshCw, Save } from 'lucide-react';
import { api, post } from './api';
import { loadLocal, saveLocal } from './drafts';
import GenerationModel from './GenerationModel';
import { AssetChoice } from './Catalog';

const ModelPreview = React.lazy(() => import('./ModelPreview'));
const labels: Record<string, string> = { draft: tr("待确认"), submitting: tr("正在提交"), queued: tr("云端排队中"), running: tr("云端生成中"), ready: tr("云端已完成 · 待导入"), importing: tr("正在下载与校验"), imported: tr("已纳入资产 · 待验收"), unknown: tr("提交结果待核对"), failed: tr("云端任务失败"), cancelled: tr("云端任务已取消"), restored: tr("恢复的历史任务") };

export default function Tripo({ data, run, busy, refresh, onAttach, onError }: any) {
  const pid = data.project.id, draftKey = 'tripo-draft:' + pid;
  const [config, setConfig] = useState<any>(null), [region, setRegion] = useState('cn'), [key, setKey] = useState('');
  const [spec, setSpec] = useState<any>(null), [jobs, setJobs] = useState<any[]>([]), [balance, setBalance] = useState<any>(null);
  const [recovery, setRecovery] = useState<Record<string, string>>({}), [view, setView] = useState('');
  const editor = useRef<HTMLDetailsElement>(null);
  const reload = async () => setJobs(await api(`/projects/${pid}/tripo`));
  useEffect(() => { run(async () => {
    const [c, m] = await Promise.all([api('/tripo/config'), api(`/projects/${pid}/generation-models`)]); setConfig(c); setRegion(c.region); setSpec(loadLocal(draftKey, { ...c.defaults, model: m.selected.tripo })); await reload();
  }); }, [pid]);
  useEffect(() => { run(reload); }, [data.runs]);
  const edit = (patch: any) => {
    const next = { ...spec, ...patch }; setSpec(next);
    try { saveLocal(draftKey, next); } catch (e) { onError((e as Error).message); }
  };
  const updateJobs = async (fn: () => Promise<any>) => { await fn(); await reload(); await refresh(); };
  return <div className="page-content tripo-workspace">
    <section className="card blender-intro"><span className="eyebrow">TRIPO V3 · CLOUD MODELING</span><h2>{tr("从文字或图片，生成三维模型。")}</h2><p>{tr("让角色建模负责人保存 Tripo 方案，或直接填写。确认后使用 Tripo API 积分生成，再将结果纳入项目资产。")}</p><p className="hint">{tr("Tripo API 需要独立 Key 与 API 积分。模型生成后仍需检查造型、拓扑和引擎效果；本页不会自动进行绑定、动画或收费后处理。")}</p><a className="text-button" href="https://developers.tripo3d.ai/en/docs/quick-start" target="_blank" rel="noreferrer">{tr("Tripo 官方 API 文档")}<ExternalLink size={12}/></a></section>
    <details className="card tripo-connection" open={!config?.configured}><summary>{config?.configured ? tr("Tripo API Key 已配置") : tr("连接 Tripo API")} · {config?.region === 'global' ? tr("全球站") : tr("中国站")}</summary><label>{tr("API 区域")}<select aria-label={tr("Tripo API 区域")} value={region} disabled={busy} onChange={e => setRegion(e.target.value)}><option value="cn">{tr("中国站 · openapi.tripo3d.com")}</option><option value="global">{tr("全球站 · openapi.tripo3d.ai")}</option></select></label><label>API Key<input aria-label="Tripo API Key" type="password" autoComplete="off" value={key} disabled={busy} onChange={e => setKey(e.target.value)} placeholder={config?.configured ? tr("已保存，留空保持不变") : tr("仅保存在本机后端，Windows 加密保存")}/></label>
      <div className="action-bar"><button className="secondary" disabled={busy} onClick={() => run(async () => { const c = await api('/tripo/config', { method: 'PUT', body: JSON.stringify({ region, key }) }); setConfig(c); setKey(''); setBalance(null); }, tr("Tripo 连接配置已保存，尚未提交生成"))}>{tr("保存连接")}</button><button className="secondary" disabled={busy || !config?.configured} onClick={() => run(async () => { setBalance(await post('/tripo/test')); setConfig(await api('/tripo/config')); }, tr("已查询 Tripo API 余额；未创建生成任务"))}>{tr("核验连接与 API 余额")}</button><button className="text-button" disabled={busy || !config?.configured} onClick={() => run(async () => { setConfig(await api('/tripo/config', { method: 'PUT', body: JSON.stringify({ clear_key: true, region: config.region }) })); setBalance(null); setKey(''); })}>{tr("清除本机保存的 Key")}</button></div>
      <p className="hint">{tr("切换区域后核对对应 Key。每份方案绑定创建时的 API 区域，查询已有任务不会自动换区。也可使用 TRIPO_API_KEY 环境变量。")}</p>
      {balance && <p>{tr("API 余额：")}{balance.balance} {tr("· 冻结积分：")}{balance.frozen ?? tr("未返回")}</p>}{config?.verified && <small className="hint">{tr("曾于")}{new Date(config.verified.checked_at).toLocaleString(dateLocale)} {tr("核验余额，真实生成仍需一次任务验证。")}</small>}
    </details>
    <GenerationModel pid={pid} service="tripo" run={run} busy={busy} onSaved={(model: string) => setSpec((old: any) => old ? { ...old, model } : old)}/>
    {spec && config && <details className="card character-editor" ref={editor}><summary>{tr("手动创建 / 调整 Tripo 方案")}</summary><div className="character-form">
      <label>{tr("方案名称")}<input aria-label={tr("Tripo 方案名称")} maxLength={100} value={spec.title} onChange={e => edit({ title: e.target.value })}/></label>
      <div className="character-fields"><label>{tr("生成方式")}<select aria-label={tr("Tripo 生成方式")} value={spec.mode} onChange={e => edit({ mode: e.target.value, prompt: '', source_asset_id: '' })}><option value="text">{tr("文字生成 3D")}</option><option value="image">{tr("图片生成 3D")}</option></select></label><label>{tr("生成模型")}<select aria-label={tr("Tripo 生成模型")} value={spec.model} onChange={e => edit({ model: e.target.value })}>{config.models.map((m: string) => <option key={m} value={m}>{m}</option>)}</select></label><label>{tr("面数目标")}<input aria-label={tr("Tripo 面数目标")} type="number" min={500} max={100000} step={500} value={spec.face_limit} onChange={e => edit({ face_limit: e.target.value ? Number(e.target.value) : '' })}/></label></div>
      {spec.mode === 'text' ? <label>{tr("模型描述（最多 1024 字符）")}<textarea aria-label={tr("Tripo 模型描述")} maxLength={1024} value={spec.prompt} onChange={e => edit({ prompt: e.target.value })} placeholder={tr("例如：穿蓝色外衣的低模探索者，清晰轮廓，完整四肢，适合游戏美术草稿")}/></label> : <><label>{tr("项目参考图")}<AssetChoice pid={pid} label={tr("Tripo 参考图")} value={spec.source_asset_id} change={(id: string) => edit({ source_asset_id: id })}/></label><p className="hint">{tr("推荐至少 256×256 像素、主体清楚的静态图片。确认生成后上传清理元数据的 PNG，最大 20 MB；本版图生接口仅使用图片。")}</p>{spec.source_asset_id && <div className="character-reference"><img src={`/api/assets/${spec.source_asset_id}/file`} alt={tr("Tripo 参考图")}/><button className="text-button" onClick={() => run(async () => onAttach(await api(`/projects/${pid}/assets/${spec.source_asset_id}`)))}>{tr("附图给左侧 AI 讨论")}</button></div>}</>}
      <div className="action-bar"><label><input type="checkbox" checked={spec.texture} onChange={e => edit({ texture: e.target.checked, pbr: e.target.checked ? spec.pbr : false })}/>{tr("生成贴图")}</label><label><input type="checkbox" checked={spec.pbr} onChange={e => edit({ pbr: e.target.checked, texture: e.target.checked || spec.texture })}/>{tr("PBR 材质")}</label></div>
      <button className="primary" disabled={busy || !spec.title.trim() || (spec.mode === 'text' ? !spec.prompt.trim() : !spec.source_asset_id)} onClick={() => run(() => updateJobs(() => post(`/projects/${pid}/tripo`, spec)), tr("Tripo 方案已保存，未上传图片或提交收费生成"))}><Save size={14}/>{tr("保存待确认方案")}</button>
    </div></details>}
    <div className="section-heading"><h2>{tr("Tripo 方案与任务")}</h2><button className="text-button" disabled={busy} onClick={() => run(reload)}><RefreshCw size={14}/>{tr("刷新本机记录")}</button></div>
    <p className="hint">{tr("向左侧负责人说明“使用 Tripo”，开启执行后可保存方案。本机记录不等于远程最新状态；点击任务的查询按钮更新，关闭工作台不会取消云端任务。")}</p>
    {!jobs.length && <div className="empty"><Box/><h3>{tr("还没有 Tripo 方案")}</h3><p>{tr("与 AI 讨论造型，或展开上方表单创建。")}</p></div>}
    {jobs.map(j => {
      const s = JSON.parse(j.spec), r = JSON.parse(j.result);
      const image = data.assets.find((a: any) => a.id === s.source_asset_id);
      return <section className="card character-job tripo-job" key={j.id}><div className="section-heading"><h3>{s.title}</h3><span className={'status ' + (['queued', 'running', 'submitting', 'importing'].includes(j.status) ? 'running' : j.status)}>{labels[j.status] || j.status}</span></div>
        <p className="character-summary">{s.mode === 'image' ? tr("图生 3D") : tr("文生 3D")} · {s.model} {tr("· 面数目标")}{s.face_limit} · {j.region === 'cn' ? tr("中国站") : tr("全球站")} · {s.texture ? tr("有贴图") : tr("纯几何")}{s.pbr ? ' / PBR' : ''}</p>
        {s.mode === 'text' ? <p>{s.prompt}</p> : <div className="character-reference">{s.source_asset_id && <img src={`/api/assets/${s.source_asset_id}/file`} alt={tr("此方案的参考图")}/>}<span>{image?.name || s.source_asset_id}</span></div>}
        {j.task_id && <p className="hint break">{tr("任务：")}{j.task_id}</p>}{r.progress != null && j.status !== 'draft' && <p className="hint">{tr("Tripo 返回进度：")}{r.progress}%</p>}{r.message && <p className="hint">{serverText(r.message)}</p>}{r.credits_consumed != null && <p className="hint">{tr("服务记录消耗：")}{r.credits_consumed} {tr("API 积分")}</p>}
        {j.status === 'draft' && <button className="primary" disabled={busy || !config?.configured} onClick={() => {
          if (!window.confirm(tr("确认向 Tripo 提交“{0}”？\n{1}\n模型：{2}\n面数目标：{3}\n区域：{4}\n\n本次会消耗 Tripo API 积分，金额以服务计费为准。提交结果不确定时不会自动重试。", s.title, s.mode === 'image' ? tr("将上传参考图：") + (image?.name || s.source_asset_id) : tr("提示词：") + s.prompt, s.model, s.face_limit, j.region === 'cn' ? tr("中国站") : tr("全球站")))) return;
          run(() => updateJobs(() => post(`/tripo/jobs/${j.id}/submit`, { confirmed: true })));
        }}>{tr("确认上传与积分，提交生成")}</button>}
        {j.task_id && !['submitting', 'importing'].includes(j.status) && <button className="secondary" disabled={busy || !config?.configured} onClick={() => run(() => updateJobs(() => post(`/tripo/jobs/${j.id}/refresh`)))}>{tr("查询 Tripo 任务结果")}</button>}
        {j.status === 'ready' && !j.model_id && <button className="primary" disabled={busy || !config?.configured || !r.has_model} onClick={() => run(() => updateJobs(() => post(`/tripo/jobs/${j.id}/import`)), tr("Tripo 模型已纳入项目资产，等待验收"))}><Download size={14}/>{tr("下载 GLB 并纳入项目")}</button>}
        {j.status === 'unknown' && !j.task_id && <div className="tripo-recovery"><p className="intake-warning">{tr("先在 Tripo 控制台核对是否已创建任务，避免重复付费。关联时人工核对方案和创建时间，本机只校验任务类型。")}</p><input aria-label={tr("Tripo 任务恢复 ID ") + s.title} value={recovery[j.id] || ''} onChange={e => setRecovery(old => ({ ...old, [j.id]: e.target.value }))} placeholder={tr("控制台的 task_...")}/><button className="secondary" disabled={busy || !config?.configured || !recovery[j.id]?.trim()} onClick={() => {
          if (window.confirm(tr("已在 Tripo 控制台核对该任务确实对应此方案？此操作只关联与查询，不创建新生成任务。"))) run(() => updateJobs(() => post(`/tripo/jobs/${j.id}/recover`, { confirmed: true, task_id: recovery[j.id].trim() })));
        }}>{tr("核对后关联已有任务")}</button></div>}
        {j.model_id && <><div className="character-preview">{view === j.id || !j.preview_id ? <React.Suspense fallback={<span>{tr("载入 3D 查看器…")}</span>}><ModelPreview url={`/api/assets/${j.model_id}/file`}/></React.Suspense> : <img src={`/api/assets/${j.preview_id}/file`} alt={s.title + tr(" Tripo 预览")}/>}</div><div className="action-bar">{j.preview_id && <button className="secondary" onClick={() => setView(view === j.id ? '' : j.id)}>{view === j.id ? tr("查看预览图") : tr("交互查看 3D")}</button>}<a className="text-button" download={s.title + '.glb'} href={`/api/assets/${j.model_id}/file`}><Download size={13}/>{tr("下载 GLB")}</a></div><p className="hint">{tr("可将 GLB 手动导入 Blender、Unity 或 Unreal 继续编辑。云端输出不等于已完成拓扑、绑定或引擎验收。")}</p></>}
        {r.preview_note && <p className="hint">{serverText(r.preview_note)}</p>}
        <div className="action-bar"><button className="text-button" disabled={j.status === 'unknown'} onClick={() => { setSpec(s); try { saveLocal(draftKey, s); } catch (e) { onError((e as Error).message); } if (editor.current) { editor.current.open = true; editor.current.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }}><Copy size={13}/>{tr("复制参数为新方案")}</button></div><details><summary>{tr("参数与生成记录")}</summary><pre>{JSON.stringify({ spec: s, result: r, task_id: j.task_id, created: j.created }, null, 2)}</pre></details>
      </section>;
    })}
  </div>;
}
