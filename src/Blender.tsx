import PathPicker from './PathPicker';
import { t as tr } from './i18n';
import React, { useEffect, useRef, useState } from 'react';
import { Box, Copy, Download, ExternalLink, RefreshCw, Save, Square } from 'lucide-react';
import { api, post } from './api';
import { loadLocal, saveLocal } from './drafts';
import { AssetChoice } from './Catalog';

const ModelPreview = React.lazy(() => import('./ModelPreview'));
const labels: Record<string, string> = { draft: tr("待确认方案"), building: tr("Blender 生成中"), review: tr("草稿已生成 · 待验收"), failed: tr("生成失败"), interrupted: tr("已中断") };
const fields: Record<string, string> = { height: tr("身高（米）"), head_ratio: tr("头高 / 身高"), shoulder_ratio: tr("肩宽 / 身高"), leg_ratio: tr("腿长 / 身高"), arm_ratio: tr("臂长 / 身高"), body_scale: tr("体型宽度倍率"), style: tr("角色模板"), outfit: tr("服装"), hair: tr("发型"), accessory: tr("配件"), pose: tr("姿态"), skin_color: tr("肤色 / 机身"), clothing_color: tr("服装颜色"), hair_color: tr("头发 / 靴子"), accent_color: tr("装饰颜色") };
const options: Record<string, string> = { human: tr("人形"), chibi: tr("大头角色"), robot: tr("机器人"), plain: tr("基础服装"), tunic: tr("束腰外衣"), armor: tr("简易护甲"), none: tr("无"), short: tr("短发"), bob: tr("齐肩发"), backpack: tr("背包"), staff: tr("手杖"), a_pose: tr("A 姿态"), t_pose: tr("T 姿态") };

export default function Blender({ data, run, busy, refresh, onAttach, onError }: any) {
  const pid = data.project.id;
  const [config, setConfig] = useState<any>(null), [path, setPath] = useState('');
  const [spec, setSpec] = useState<any>(null), [parent, setParent] = useState('');
  const [jobs, setJobs] = useState<any[]>([]), [logs, setLogs] = useState<Record<string, string>>({});
  const [view, setView] = useState('');
  const form = useRef<HTMLDetailsElement>(null);
  const key = 'character:' + pid;
  const reload = async () => setJobs(await api(`/projects/${pid}/characters`));
  const edit = (changes: any) => {
    const next = { ...spec, ...changes };
    setSpec(next);
    try { saveLocal(key, { spec: next, parent }); } catch (e) { onError((e as Error).message); }
  };
  useEffect(() => { run(async () => {
    const c = await api('/blender/config'); setConfig(c); setPath(c.executable);
    const saved = loadLocal(key, { spec: c.defaults, parent: '' });
    setSpec(saved.spec); setParent(saved.parent); await reload();
  }); }, [pid]);
  useEffect(() => { run(reload); }, [data.runs]);
  const building = jobs.some(j => j.status === 'building');
  useEffect(() => {
    if (!building) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api(`/projects/${pid}/characters`);
        if (!active) return;
        setJobs(value);
        if (!value.some((j: any) => j.status === 'building')) { await refresh(); return; }
        timer = setTimeout(poll, 1500);
      } catch (e) { if (active) run(async () => { throw e; }); }
    };
    timer = setTimeout(poll, 1500);
    return () => { active = false; clearTimeout(timer); };
  }, [building, pid]);
  const copy = (j: any) => {
    const value = { spec: JSON.parse(j.spec), parent: j.id };
    setSpec(value.spec); setParent(value.parent); saveLocal(key, value);
    if (form.current) { form.current.open = true; form.current.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  };
  return <div className="page-content blender-workspace">
    <section className="card blender-intro"><span className="eyebrow">CHARACTER LAB · LOCAL BLENDER</span><h2>{tr("先设计比例，再生成角色。")}</h2><p>{tr("与左侧角色建模负责人讨论，开启“执行”让 AI 保存方案；审阅后点击本机生成。也可以直接调整下方参数。")}</p><p className="hint">{tr("可编辑的低模分件草稿，适合造型探索。尚未自动绑定、雕刻或进行引擎验收。参考图用于 AI 讨论，不会自动重建为三维模型。")}</p></section>
    <details className="card blender-connection"><summary>{config?.available ? tr("已发现 {0}", config.version) : tr("设置本机 Blender")} <span className="hint">{tr("· 点击配置路径")}</span></summary><label>{tr("Blender 程序路径")}<input aria-label={tr("Blender 程序路径")} value={path} onChange={e => setPath(e.target.value)} placeholder={tr("blender.exe 的完整路径；留空自动发现")}/><PathPicker purpose="blender" value={path} change={setPath} run={run} disabled={busy}/></label><button className="secondary" disabled={busy} onClick={() => run(async () => { const c = await api('/blender/config', { method: 'PUT', body: JSON.stringify({ executable: path }) }); setConfig(c); setPath(c.executable); })}>{tr("保存并检查连接")}</button>{config?.error && <p className="hint">{config.error}</p>}</details>
    {spec && config && <details className="card character-editor" ref={form}><summary>{tr("手动创建 / 调整角色方案")}</summary><div className="character-form">
      <div className="section-heading"><h2>{parent ? tr("派生新方案") : tr("新角色方案")}</h2>{parent && <button className="text-button" onClick={() => { setParent(''); saveLocal(key, { spec, parent: '' }); }}>{tr("取消版本关联")}</button>}</div>
      <label>{tr("角色名称")}<input aria-label={tr("角色名称")} value={spec.title} maxLength={100} onChange={e => edit({ title: e.target.value })}/></label>
      <label>{tr("设计说明")}<textarea aria-label={tr("角色设计说明")} value={spec.brief} maxLength={4000} onChange={e => edit({ brief: e.target.value })} placeholder={tr("例如：探索废墟的少年，蓝色束腰外衣与旅行背包。实际形状由下面的参数控制。")}/></label>
      <div className="character-fields">{Object.entries(config.choices).map(([k, values]: any) => <label key={k}>{fields[k]}<select aria-label={fields[k]} value={spec[k]} onChange={e => {
        if (k === 'style') edit(e.target.value === 'chibi' ? { style: 'chibi', head_ratio: .29, leg_ratio: .38 } : { style: e.target.value });
        else edit({ [k]: e.target.value });
      }}>{values.map((v: string) => <option key={v} value={v}>{options[v]}</option>)}</select></label>)}</div>
      <div className="character-fields">{Object.entries(config.ranges).map(([k, range]: any) => <label key={k}>{fields[k]}<input aria-label={fields[k]} type="number" min={range[0]} max={range[1]} step="0.01" value={spec[k]} onChange={e => edit({ [k]: e.target.value === '' ? '' : Number(e.target.value) })}/></label>)}</div>
      <div className="character-colors">{['skin_color', 'clothing_color', 'hair_color', 'accent_color'].map(k => <label key={k}><input aria-label={fields[k]} type="color" value={spec[k]} onChange={e => edit({ [k]: e.target.value })}/><span>{fields[k]}<small>{spec[k]}</small></span></label>)}</div>
      <label>{tr("设计参考图")}<AssetChoice pid={pid} label={tr("角色参考图")} value={spec.reference_asset_id} change={(id: string) => edit({ reference_asset_id: id })}/></label>
      {spec.reference_asset_id && <div className="character-reference"><img alt={tr("角色设计参考图")} src={`/api/assets/${spec.reference_asset_id}/file`}/><button className="text-button" onClick={() => run(async () => onAttach(await api(`/projects/${pid}/assets/${spec.reference_asset_id}`)))}>{tr("附图给左侧 AI 讨论")}</button></div>}
      <button className="primary" disabled={busy || !spec.title.trim()} onClick={() => run(async () => { await post(`/projects/${pid}/characters`, { spec, parent_id: parent || null }); await reload(); }, tr("角色方案已保存；审阅后可在本机生成"))}><Save size={15}/>{tr("保存待确认方案")}</button><small className="hint">{tr("修改参数需保存为新方案。现有模型与源文件会保留。")}</small>
    </div></details>}
    <div className="section-heading"><h2>{tr("角色方案与交付物")}</h2><button className="text-button" disabled={busy} onClick={() => run(async () => { await reload(); await refresh(); })}><RefreshCw size={14}/>{tr("刷新")}</button></div>
    {!jobs.length && <div className="empty-state"><Box/><h3>{tr("还没有角色方案")}</h3><p>{tr("让 AI 保存设计方案，或填写上方参数。")}</p></div>}
    {jobs.map(j => {
      const s = JSON.parse(j.spec), r = JSON.parse(j.result);
      return <section className="card character-job" key={j.id}>
        <div className="section-heading"><h3>{s.title}</h3><span className={'status ' + (j.status === 'building' ? 'running' : j.status)}>{labels[j.status] || j.status}</span></div>
        <p className="character-summary">{options[s.style]} · {s.height} {tr("米 ·")}{options[s.outfit]} · {options[s.hair]} · {options[s.accessory]} · {options[s.pose]}</p>
        {s.brief && <p>{s.brief}</p>}
        <div className="character-recipe"><span>{tr("头高")}{s.head_ratio} {tr("/ 肩宽")}{s.shoulder_ratio}</span><span>{tr("腿长")}{s.leg_ratio} {tr("/ 臂长")}{s.arm_ratio} {tr("/ 体宽")}{s.body_scale}</span><span className="character-swatches">{['skin_color', 'clothing_color', 'hair_color', 'accent_color'].map(k => <i key={k} title={fields[k] + ' ' + s[k]} style={{ background: s[k] }}/>)}</span></div>
        {j.parent_id && <small className="hint">{tr("派生自方案")}{j.parent_id.slice(0, 8)}</small>}
        {s.reference_asset_id && <small className="hint">{tr("设计参考图：")}{data.assets.find((a: any) => a.id === s.reference_asset_id)?.name || s.reference_asset_id}</small>}
        {j.status === 'draft' && <button className="primary" disabled={busy || building || !config?.available} onClick={() => run(async () => { await post(`/characters/${j.id}/build`, { confirmed: true }); await reload(); await refresh(); })}><Box size={15}/>{tr("按以上参数在 Blender 生成草稿")}</button>}
        {j.status === 'building' && <div className="action-bar"><span className="hint">{tr("本机后台建模与渲染中，最长 3 分钟…")}</span><button className="secondary" disabled={busy} onClick={() => run(async () => { await post(`/characters/${j.id}/cancel`); await reload(); })}><Square size={13}/>{tr("停止生成")}</button></div>}
        {r.error && <p className="hint">{r.error}{tr("。可复制调整后重新保存方案。")}</p>}
        {j.status === 'review' && <>
          <div className="character-preview">{view === j.id ? <React.Suspense fallback={<span>{tr("载入 3D 查看器…")}</span>}><ModelPreview url={`/api/assets/${j.model_id}/file`}/></React.Suspense> : <img src={`/api/assets/${j.preview_id}/file`} alt={s.title + tr(" Blender 渲染预览")}/>}</div>
          <div className="action-bar"><button className="secondary" onClick={() => setView(view === j.id ? '' : j.id)}>{view === j.id ? tr("查看渲染图") : tr("交互查看 3D")}</button><button className="secondary" disabled={busy} onClick={() => run(() => post(`/characters/${j.id}/open`), tr("已请求在 Blender 中打开源文件"))}><ExternalLink size={14}/>{tr("在 Blender 中编辑")}</button></div>
          <div className="action-bar"><a className="text-button" href={`/api/assets/${j.model_id}/file`} download={s.title + '.glb'}><Download size={13}/>{tr("GLB 模型")}</a><a className="text-button" href={`/api/assets/${j.source_id}/file`} download={s.title + '.blend'}><Download size={13}/>{tr("Blender 源文件")}</a></div>
          <p className="hint">{r.stats?.objects} {tr("个网格部件 ·")}{r.stats?.vertices} {tr("顶点 ·")}{r.stats?.triangles} {tr("三角形 · Blender")}{r.stats?.blender}<br/>{tr("未绑定，部件未连接；用于造型草稿，需美术验收后进入引擎。")}</p>
        </>}
        <div className="action-bar"><button className="text-button" onClick={() => copy(j)}><Copy size={13}/>{tr("复制参数并调整")}</button><button className="text-button" disabled={busy} onClick={() => run(async () => { const v = await api(`/characters/${j.id}/logs`); setLogs(old => ({ ...old, [j.id]: v.text })); })}>{tr("查看生成日志")}</button></div>
        <details><summary>{tr("完整参数与生成依据")}</summary><pre>{JSON.stringify({ id: j.id, parent_id: j.parent_id, spec: s, result: r }, null, 2)}</pre></details>{logs[j.id] && <pre className="character-log">{logs[j.id]}</pre>}
      </section>;
    })}
  </div>;
}
