import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { api, post } from './api';
import { loadLocal, saveLocal } from './drafts';
import { AssetChoice } from './Catalog';

export function WebUIFields({ value, change, catalog }: any) {
  const [filter, setFilter] = useState('');
  const loras = value.loras || [];
  const update = (id: string, weight?: number) => change({ ...value, loras: weight === undefined ? loras.filter((l: any) => l.id !== id) : [...loras.filter((l: any) => l.id !== id), { id, weight }] });
  return <div className="webui-fields">
    <label>{tr("主模型 Checkpoint")}<select aria-label={tr("WebUI 主模型")} value={value.checkpoint || ''} onChange={e => change({ ...value, checkpoint: e.target.value })}><option value="">{tr("请选择模型")}</option>{catalog?.checkpoints?.map((m: any) => <option key={m.id} value={m.id}>{m.title} {!m.available ? tr("· 离线目录") : ''}</option>)}</select></label>
    <div className="webui-parameters">{[['width', tr("宽度"), 64, 2048, 8], ['height', tr("高度"), 64, 2048, 8], ['steps', tr("步数"), 1, 100, 1], ['cfg_scale', 'CFG', 1, 30, 0.5], ['seed', tr("Seed（-1 随机）"), -1, 4294967295, 1], ['denoising_strength', tr("图生图重绘幅度"), 0, 1, 0.05]].map(([key, label, min, max, step]) => <label key={key}> {label}<input aria-label={'WebUI ' + label} type="number" min={min} max={max} step={step} value={value[key] ?? ''} onChange={e => change({ ...value, [key]: Number(e.target.value) })}/></label>)}</div>
    <label>{tr("采样器")}<select aria-label={tr("WebUI 采样器")} value={value.sampler || ''} onChange={e => change({ ...value, sampler: e.target.value })}>{Array.from(new Set([value.sampler || 'Euler a', ...(catalog?.samplers || [])])).map((s: any) => <option key={s} value={s}>{s}</option>)}</select></label>
    <label>{tr("负面提示词")}<textarea aria-label={tr("WebUI 负面提示词")} value={value.negative_prompt || ''} onChange={e => change({ ...value, negative_prompt: e.target.value })}/></label>
    <details className="lora-selector"><summary>{tr("LoRA · 已选")}{loras.length} / 8</summary><input aria-label={tr("筛选 LoRA")} value={filter} onChange={e => setFilter(e.target.value)} placeholder={tr("按名称搜索 LoRA")}/>{catalog?.loras?.filter((m: any) => (m.name + m.alias).toLowerCase().includes(filter.toLowerCase())).map((m: any) => {
      const selected = loras.find((l: any) => l.id === m.id);
      return <div className="lora-row" key={m.id}><label><input type="checkbox" checked={!!selected} disabled={!selected && loras.length >= 8} onChange={e => update(m.id, e.target.checked ? 0.8 : undefined)}/><span>{m.name}<small>{m.base_model || tr("基底未声明")} · {m.alias}</small></span></label>{selected && <input type="number" aria-label={tr("LoRA 权重：") + m.name} min="-2" max="2" step="0.1" value={selected.weight} onChange={e => update(m.id, Number(e.target.value))}/>}</div>;
    })}<small>{tr("需要与主模型匹配；本版不自动判定兼容性或补全触发词。请在正面提示词中填写所需触发词。")}</small></details>
  </div>;
}

export function ArtRecords({ records }: any) {
  if (!records?.length) return <p className="hint">{tr("尚无生成或导入记录。")}</p>;
  const decode = (value: string) => { try { return JSON.parse(value); } catch { return value; } };
  return <div className="art-records">{records.map((r: any) => <details key={r.id}><summary>{r.provider} · {r.status} · {new Date(r.created).toLocaleString(dateLocale)}</summary>{r.asset_id && <a className="text-button" href={`/api/assets/${r.asset_id}/file`} target="_blank" rel="noreferrer">{tr("查看 / 下载项目图片")}</a>}<pre>{JSON.stringify({ parameters: decode(r.spec), result: decode(r.result) }, null, 2)}</pre></details>)}</div>;
}

export default function ImageComposer({ data, run, refresh, asset, info, onResult, onSetup }: any) {
  const [provider, setProvider] = useState(() => loadLocal('image-provider', 'openai'));
  const [prompt, setPrompt] = useState(''), [mask, setMask] = useState(''), [working, setWorking] = useState(false), [notice, setNotice] = useState('');
  const [catalog, setCatalog] = useState<any>(null), [params, setParams] = useState<any>({});
  const reload = async () => {
    const [cfg, cat] = await Promise.all([api('/webui/config'), api('/webui/catalog')]);
    setCatalog(cat);
    setParams((previous: any) => Object.keys(previous).length ? previous : { ...cfg.defaults, checkpoint: cfg.defaults.checkpoint || cat.checkpoints.find((m: any) => m.title === cat.current_checkpoint)?.id || '' });
  };
  useEffect(() => { let active = true; if (provider === 'webui') {
    Promise.all([api('/webui/config'), api('/webui/catalog')]).then(([cfg, cat]) => { if (active) { setCatalog(cat); setParams((previous: any) => Object.keys(previous).length ? previous : { ...cfg.defaults, checkpoint: cfg.defaults.checkpoint || cat.checkpoints.find((m: any) => m.title === cat.current_checkpoint)?.id || '' }); } }).catch(e => { if (active) setNotice(e.message); });
  } return () => { active = false; }; }, [provider]);
  const generate = () => run(async () => {
    setWorking(true); setNotice('');
    try {
      const body = { ...(provider === 'webui' ? params : {}), provider, prompt, expected_hash: info?.hash, mask_asset_id: mask || undefined };
      const result = await post(asset ? `/assets/${asset.id}/ai-edit` : `/projects/${data.project.id}/generate-image`, body);
      setNotice(result.note || tr("生成候选已保存到项目资产，等待人工验收"));
      if (onResult) onResult(result.asset || result);
      await refresh();
    } finally { setWorking(false); }
  });
  return <div className="image-composer"><label>{tr("绘画来源")}<select aria-label={asset ? tr("图片编辑来源") : tr("绘画来源")} disabled={working} value={provider} onChange={e => { setProvider(e.target.value); try { saveLocal('image-provider', e.target.value); } catch (e) { setNotice((e as Error).message); } }}><option value="openai">{tr("OpenAI 图像 API")}</option><option value="webui">{tr("本机 Stable Diffusion WebUI")}</option></select></label>
    <textarea aria-label={asset ? tr("AI 图片编辑需求") : tr("美术生成需求")} value={prompt} disabled={working} onChange={e => setPrompt(e.target.value)} placeholder={asset ? tr("说明修改目标和需保留内容…") : tr("描述场景、风格、构图和用途…")}/>
    {provider === 'webui' && <><div className="action-bar"><span className={'status ' + (catalog?.online ? 'done' : 'blocked')}>{catalog?.online ? tr("API 已连接") : tr("离线 / 尚未连接")}</span><button className="text-button" disabled={working} onClick={() => run(reload)}><RefreshCw size={13}/>{tr("刷新目录")}</button>{onSetup && <button className="text-button" disabled={working} onClick={onSetup}>{tr("WebUI 设置")}</button>}</div><p className="hint">{catalog?.message || tr("读取本机模型目录…")}</p><fieldset className="webui-request-fields" disabled={working}><WebUIFields value={params} change={setParams} catalog={catalog}/></fieldset><p className="hint">{tr("本机 GPU 生成 · 一次一张 · 不改 WebUI 全局模型设置。请勿在等待期间重复提交。")}</p></>}
    {asset && <label>{tr("局部编辑遮罩")}<AssetChoice pid={data.project.id} label={tr("编辑遮罩")} value={mask} disabled={working} exclude={asset.id} change={setMask}/><small>{tr("同尺寸透明 PNG；完全透明区域表示希望编辑的位置。结果需人工检查。")}</small></label>}
    {provider === 'openai' && <p className="hint">{tr("使用独立 OpenAI 图像 API 并计费；需先配置 Key 与图像模型。")}</p>}
    <button className="primary full-width" disabled={working || !prompt.trim() || (asset && !info) || (provider === 'webui' && (!catalog?.online || !params.checkpoint))} onClick={generate}>{working ? <LoaderCircle size={15} className="spin"/> : <Sparkles size={15}/>} {working ? tr("正在生成，请等待并核对结果…") : asset ? tr("生成编辑候选并保存") : tr("生成一张候选")}</button>
    {notice && <p className="hint" role="status">{notice}</p>}
  </div>;
}
