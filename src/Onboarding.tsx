import { language, t as tr, serverText } from './i18n';
import { useEffect, useState } from 'react';
import { api, post } from './api';

const features = [
  ['core', tr('项目管理'), tr('设计、任务、资产与快照；无需 AI 账号'), 'overview'],
  ['codex', tr('Codex 会员对话'), tr('装配本机入口后，在官方页面登录'), 'connections'],
  ['api', tr('OpenAI / DeepSeek API'), tr('填写自己的 Key 和模型，无需本机大模型'), 'connections'],
  ['music', tr('音乐创作'), tr('装配 Node 与原版 Skill，再完成网页授权'), 'music'],
  ['blender', tr('本机角色建模'), tr('发现或装配 Blender，再生成参数化草稿'), 'blender'],
  ['tripo', tr('Tripo 云端建模'), tr('无需安装本机模型；在建模页配置 Key 和额度'), 'blender'],
  ['webui', tr('本机绘画'), tr('连接已有 WebUI，模型和 LoRA 由你选择'), 'webui'],
  ['github', tr('GitHub 项目发布'), tr('装配 Git，再配置仓库与上传权限'), 'management'],
  ['engines', tr('Unreal / Unity 引擎'), tr('按引擎官方指引安装、许可并接入工程'), 'connections'],
];
const toolNames: Record<string, string> = { node: 'Node.js LTS', codex: 'Codex CLI', git: 'Git', blender: 'Blender', suno: 'Suno.cn Skill' };
const guides = [
  ['api', 'OpenAI API', 'https://platform.openai.com/api-keys'], ['api', 'DeepSeek API', 'https://platform.deepseek.com/api_keys'],
  ['tripo', 'Tripo', 'https://platform.tripo3d.ai/'],
  ['node', 'Node.js', 'https://nodejs.org/en/download'], ['codex', 'Codex', 'https://learn.chatgpt.com/docs/codex/cli'],
  ['git', 'Git', 'https://git-scm.com/downloads'], ['blender', 'Blender', 'https://www.blender.org/download/'],
  ['music', 'Suno.cn Skill', 'https://mcp.suno.cn/mcp/skill/setup.md'], ['webui', 'WebUI', 'https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Installation-on-Windows-10-and-11-64-bit'],
  ['engines', 'Unreal Engine', 'https://www.unrealengine.com/download'], ['engines', 'Unity', 'https://unity.com/download'],
];
const states: Record<string, string> = { running: tr('正在装配'), succeeded: tr('命令已结束，连接待验证'), failed: tr('装配未完成'), unknown: tr('安装状态待核对'), interrupted: tr('装配已中断') };

export default function Onboarding({ run, busy, setPage, onPractice, onImport, hasProject }: any) {
  const [value, setValue] = useState<any>(null), [error, setError] = useState(''), [selected, setSelected] = useState<string[]>(['core']);
  const [step, setStep] = useState(1), [plan, setPlan] = useState<any>(null), [engine, setEngine] = useState('unreal');
  const load = async () => { const next = await api('/onboarding'); setValue(next); return next; };
  useEffect(() => { let active = true; api('/onboarding').then(v => { if (active) { setValue(v); setSelected(v.features); } }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  const running = value?.installations.some((v: any) => v.status === 'running');
  useEffect(() => { if (!running) return; let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => { try { const v = await api('/onboarding'); if (active) setValue(v); } catch (e) { if (active) setError((e as Error).message); } if (active) timer = setTimeout(poll, 1500); };
    timer = setTimeout(poll, 1500); return () => { active = false; clearTimeout(timer); };
  }, [running]);
  const save = async (seen = false) => api('/onboarding', { method: 'PUT', body: JSON.stringify({ features: selected, ...(seen ? { seen: true } : {}) }) });
  const wanted = [...(selected.some(v => ['codex', 'music'].includes(v)) ? ['node'] : []), ...selected.filter(v => ['codex', 'blender'].includes(v)), ...(selected.includes('music') ? ['suno'] : []), ...(selected.includes('github') ? ['git'] : [])];
  return <div className="page-content onboarding-page">
    <section className="card onboarding-intro"><span className="eyebrow">START HERE</span><h2>{tr('先用起来，再按需启用创作工具。')}</h2><p>{tr('项目管理可以先独立使用。选择你需要的功能，工作台发现已有程序，缺少的支持工具可按清单装配。')}</p><div className="action-bar">{[tr('1 检查基础'), tr('2 选择与装配'), tr('3 开始创作')].map((label, i) => <button key={i} disabled={busy || running} className={step === i + 1 ? 'primary' : 'secondary'} onClick={() => run(async () => { if (step === 2) await save(); setStep(i + 1); })}>{label}</button>)}</div></section>
    {error && <p role="alert">{error}</p>}
    {!value ? <p>{tr('正在发现本机工具…')}</p> : <>
      {step === 1 && <section className="card"><h2>{value.report.core_missing ? tr('基础环境仍有待处理项') : tr('基础文件已发现，可以开始练习')}</h2><p>{tr('文件发现不等于账号连接或生成已验证；缺少可选工具不妨碍先管理项目。')}</p>{value.report.write_probe && <p>{serverText(value.report.checks.find((v: any) => v.key === 'data_write')?.message)}</p>}<div className="onboarding-tools">{Object.entries(value.installed).map(([key, found]) => <p key={key}><strong>{toolNames[key]}</strong><span>{found ? tr('程序已发现，连接待核验') : tr('按需装配')}</span></p>)}</div><div className="action-bar"><button disabled={busy} onClick={() => run(async () => { const report = await post('/diagnostics/check', { write_probe: true }); setValue((old: any) => ({ ...old, report })); })}>{tr('检查数据目录读写')}</button><button disabled={busy} onClick={() => setPage('diagnostics')}>{tr('查看完整诊断')}</button><button className="primary" disabled={busy} onClick={() => setStep(2)}>{tr('选择需要的功能')}</button></div></section>}
      {step === 2 && <>
        <div className="onboarding-features">{features.map(([id, title, detail]) => <label className="card" key={id}><span><input type="checkbox" aria-label={title} disabled={id === 'core' || busy || running} checked={selected.includes(id)} onChange={e => { setSelected(old => e.target.checked ? [...old, id] : old.filter(v => v !== id)); setPlan(null); }}/><strong>{title}</strong></span><p>{detail}</p></label>)}</div>
        <section className="card"><h2>{tr('按选择装配支持工具')}</h2><p>{tr('只装配缺少的工具。系统程序来自 WinGet；Codex 与原版 SUNO Skill 装入工作台数据目录，保留已有全局安装和账号凭据。')}</p><div className="action-bar"><button className="secondary" disabled={busy || running || !wanted.length} onClick={() => run(async () => { await save(); setPlan(await post('/onboarding/plan', { tools: wanted })); })}>{tr('查看装配清单')}</button><button disabled={busy || running} onClick={() => run(async () => { await save(); setStep(3); })}>{tr('保存选择并继续')}</button></div>{plan && <div className="onboarding-plan"><h3>{plan.steps.length ? tr('准备安装以下工具') : tr('所选支持程序均已发现，无需安装')}</h3>{plan.steps.map((v: any) => <p key={v.tool}><strong>{toolNames[v.tool]}</strong><small>{v.source} · {['codex', 'suno'].includes(v.tool) ? tr('当前工作台数据目录') : tr('Windows 程序安装目录')}</small><details><summary>{tr('查看具体安装位置')}</summary><code className="break">{v.destination}</code></details></p>)}<p>{tr('需要联网和可用磁盘。Windows 可能要求管理员确认；若出现许可或来源协议，请本人完成，工作台不会代为接受。')}</p>{plan.steps.length > 0 && <button className="primary" disabled={busy || running} onClick={() => run(async () => { await post('/onboarding/install', { plan_id: plan.id, confirmed: true }); setPlan(null); await load(); })}>{tr('按此清单装配')}</button>}</div>}<p className="hint">{tr('没有 WinGet 或安装失败时，可使用下方官方指引。WebUI 大模型、引擎许可和账号登录需本人选择与完成。')}</p></section>
      </>}
      {(running || value.installations.length > 0) && <section className="card"><h2>{tr('装配记录')}</h2>{value.installations.map((row: any) => <div className="onboarding-installation" key={row.id}><strong>{states[row.status] || row.status}</strong><p>{row.current && toolNames[row.current]} {serverText(row.message)}</p>{row.status === 'running' && <p>{tr('请留意系统安装器；装配结束前不要关闭工作台。')}</p>}{row.status === 'unknown' && <button disabled={busy} onClick={() => run(async () => { if (window.confirm(tr('已在系统中确认原安装器结束？此操作只重新检测，不会重试安装。'))) { await post(`/onboarding/installations/${row.id}/check`, { installer_closed: true }); await load(); } })}>{tr('确认安装器结束并重新检测')}</button>}{row.log_file && <details><summary>{tr('本机安装日志位置')}</summary><p className="path-note break">{row.log_file}</p></details>}</div>)}<button disabled={busy} onClick={() => run(load)}>{tr('重新检测工具')}</button></section>}
      {step === 3 && <>
        <section className="card"><h2>{tr('三分钟练习：先留下第一份项目记录')}</h2><p>{tr('练习项目只包含总纲、入门文档和待执行任务，不调用 AI、不消耗积分，也不创建真实引擎工程。')}</p><label>{tr('引擎偏好')}<select aria-label={tr('练习项目引擎')} value={engine} onChange={e => setEngine(e.target.value)}><option value="unreal">Unreal Engine</option><option value="unity">Unity</option></select></label><div className="action-bar"><button className="primary" disabled={busy || running} onClick={() => run(async () => { const p = await post('/onboarding/practice', { language, engine }); await onPractice(p); })}>{tr('创建或打开练习项目')}</button><button disabled={busy || running} onClick={onImport}>{tr('接入我的已有游戏')}</button></div></section>
        <section className="card"><h2>{tr('启用你选择的功能')}</h2>{features.filter(([id]) => selected.includes(id)).map(([id, title, detail, page]) => <div className="onboarding-next" key={id}><div><strong>{title}</strong><p>{detail}</p></div><button disabled={busy || (!hasProject && ['music', 'blender', 'management'].includes(page))} onClick={() => run(async () => { await save(true); setPage(page); })}>{tr('打开对应设置')}</button></div>)}{!hasProject && <p className="hint">{tr('音乐、建模与项目发布先选择项目；可先创建上方练习项目。')}</p>}{selected.includes('music') && <p>{tr('在第二步勾选音乐并装配原版 Skill；进入音乐页点击授权验证，在供应方网页完成本人登录。')}</p>}</section>
      </>}
      <section className="card"><h2>{tr('官方安装与授权指引')}</h2><div className="action-bar">{guides.filter(([id]) => selected.includes(id) || wanted.includes(id)).map(([id, title, url]) => <a className="text-button" key={title} href={url} target="_blank" rel="noreferrer">{title} ↗</a>)}</div><p className="hint">{tr('安装与发现文件之后，还需在各工作区验证登录、连接及实际产出。向导不会开通付费服务或授予 Agent 权限。')}</p></section>
      <div className="action-bar"><button disabled={busy || running} onClick={() => run(async () => { await save(true); setPage('overview'); })}>{tr('完成或稍后配置，进入工作台')}</button><small>{tr('以后可随时从“快速上手”重新打开。')}</small></div>
    </>}
  </div>;
}
