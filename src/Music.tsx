import { serverText } from './i18n';
import { t as tr } from './i18n';
import { useEffect, useState } from 'react';
import { ExternalLink, Music2, RefreshCw } from 'lucide-react';
import { api, post } from './api';
import GenerationModel from './GenerationModel';

const labels: Record<string, string> = { draft: tr("待确认"), submitting: tr("正在提交"), submitted: tr("已提交"), processing: tr("生成中"), completed: tr("生成完成 · 待验收"), failed: tr("生成失败"), unknown: tr("结果待核对"), needs_credits: tr("积分不足 · 等待处理"), restored: tr("恢复的历史记录") };

export default function Music({ data, run, busy, refreshProject, setPage }: any) {
  const [connection, setConnection] = useState<any>(null), [jobs, setJobs] = useState<any[]>([]);
  const [title, setTitle] = useState(''), [prompt, setPrompt] = useState(''), [tags, setTags] = useState('');
  const [instrumental, setInstrumental] = useState(true), [action, setAction] = useState<any>(null);
  const [mv, setMv] = useState('');
  const [operationId, setOperationId] = useState(''), [operationState, setOperationState] = useState(''), [audioAck, setAudioAck] = useState('');
  const refresh = async () => setJobs(await api(`/projects/${data.project.id}/music`));
  useEffect(() => { run(async () => setConnection(await api('/music/connection'))); }, [data.project.id]);
  useEffect(() => { run(refresh); }, [data.project.id, data.runs]);
  useEffect(() => {
    if (!operationId) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const r = await api(`/projects/${data.project.id}/jobs/inspect?kind=operation&id=${operationId}`); if (!active) return;
        setOperationState(({ queued: tr("排队中"), running: tr("查询 / 下载中"), succeeded: tr("本机操作完成，请检查音轨与资产"), failed: tr("操作失败，请到作业中心查看原因"), needs_user: tr("需要处理账户或来源状态"), cancelled: tr("已停止本机操作"), interrupted: tr("已中断，未自动重提生成") } as any)[r.details.status] || r.details.status);
        if (!['queued', 'running'].includes(r.details.status)) { await refresh(); await refreshProject(); return; }
      } catch { if (active) setOperationState(tr("暂时无法读取作业，可到作业中心继续核对")); }
      if (active) timer = setTimeout(poll, 1500);
    };
    poll(); return () => { active = false; clearTimeout(timer); };
  }, [operationId, data.project.id]);
  const authorize = () => run(async () => { const result = await post('/music/authorize'); setConnection(result); setAction(result.action); });
  return <div className="page-content music-workspace">
    <section className="card connection-card"><div className="connection-heading"><Music2/><div><h2>{tr("Suno.cn 音乐 Skill")}</h2><p>{tr("专职音乐负责人 · 使用左侧选择的对话模型")}</p></div></div><div className="connection-body">
      <p>{!connection ? tr("读取连接状态…") : !connection.installed ? tr("本机尚未安装 suno-cn-music Skill 或 Node.js") : connection.status === 'authorized' ? tr("已获 Suno.cn 授权") : connection.message || tr("尚未完成网页授权")}</p>{connection && !connection.installed && <button className="secondary" disabled={busy} onClick={() => setPage('onboarding')}>{tr('打开快速上手装配音乐')}</button>}
      {connection?.account && <p>{tr("积分：")}{connection.account.points ?? tr("服务未返回")} {tr("· 会员：")}{String(connection.account.vip_status ?? tr("服务未返回"))}</p>}
      <button className="primary" disabled={busy} onClick={authorize}>{tr("登录授权 / 核验账户")}</button>
      <p className="hint">{tr("账号与积分属于 Suno.cn。本机安装的原版 Skill 管理凭据；工作台不读取其凭据文件。对话用量与音乐积分分别计算。")}</p>
      {action?.url && <div className="music-action"><a href={action.url} target="_blank" rel="noreferrer">{tr("打开服务端授权或处理页面")}<ExternalLink size={13}/></a><code>{action.url}</code></div>}
    </div></section>
    <GenerationModel pid={data.project.id} service="suno" run={run} busy={busy} onSaved={setMv}/>
    <div className="section-heading"><h2>{tr("音乐方案与生成任务")}</h2><button className="text-button" disabled={busy} onClick={() => run(refresh)}><RefreshCw size={14}/>{tr("刷新方案")}</button></div>
    <p className="hint">{tr("让左侧音乐负责人梳理场景与风格，开启“执行”后可保存方案。也可直接填写。保存方案不消耗音乐积分，未授自动积分权限时，提交生成需要单独确认。")}</p>
    <div className="card music-draft"><label>{tr("音乐名称")}<input aria-label={tr("音乐名称")} value={title} maxLength={120} onChange={e => setTitle(e.target.value)}/></label><label>{tr("风格标签")}<input aria-label={tr("音乐风格")} value={tags} maxLength={1000} onChange={e => setTags(e.target.value)} placeholder={tr("例如：木吉他、温暖、轻节奏")}/></label><label>{tr("创作描述（非逐字歌词）")}<textarea aria-label={tr("音乐创作需求")} value={prompt} maxLength={8000} onChange={e => setPrompt(e.target.value)}/></label><label className="check-row"><input type="checkbox" checked={instrumental} onChange={e => setInstrumental(e.target.checked)}/>{tr("纯音乐 · 不生成演唱人声")}</label><button className="secondary" disabled={busy || !title.trim() || !prompt.trim()} onClick={() => run(async () => { await post(`/projects/${data.project.id}/music`, { title, prompt, tags, instrumental, ...(mv ? { mv } : {}) }); setTitle(''); setPrompt(''); setTags(''); await refresh(); }, tr("音乐方案已保存，尚未提交生成"))}>{tr("保存待确认方案")}</button></div>
    {jobs.map(job => {
      const spec = JSON.parse(job.spec), result = JSON.parse(job.result), serials = JSON.parse(job.serials);
      return <section className="card music-job" key={job.id}><div className="section-heading"><h3>{spec.title}</h3><span>{labels[job.status] || job.status}</span></div><p>{spec.mv || (job.status === 'draft' ? tr("chirp-hawk（旧草稿默认）") : tr("模型未记录"))} · {spec.tags || tr("风格未单独指定")} · {spec.instrumental ? tr("纯音乐") : tr("允许演唱人声")}</p><pre>{spec.prompt}</pre>
        {job.status === 'draft' && <button className="primary" disabled={busy || connection?.status !== 'authorized'} onClick={() => {
          if (!window.confirm(tr("确认提交音乐“{0}”？\n模型：{1}\n风格：{2}\n{3}\n\n本次会消耗 Suno.cn 积分，具体以服务计费为准。提交后不自动重试。", spec.title, spec.mv || tr("chirp-hawk（旧方案默认）"), spec.tags || tr("按创作描述"), spec.instrumental ? tr("纯音乐") : tr("允许人声")))) return;
          run(async () => { const r = await post(`/music/jobs/${job.id}/submit`, {confirmed:true}); if (r.action) setAction(r.action); if (r.connection) setConnection((old: any) => ({...old, ...r.connection})); if (r.status === 'error') throw new Error(r.message || tr("音乐查询失败")); await refresh(); });
        }}>{tr("确认方案并提交生成（消耗积分）")}</button>}
        {!!serials.length && <button className="secondary" disabled={busy} onClick={() => run(async () => { const r = await post(`/projects/${data.project.id}/jobs/commands`, { kind: 'music', id: job.id, command: 'query' }); setOperationId(r.id); })}>{tr("排队查询已有任务")}</button>}
        {result.message && <p className="hint">{serverText(result.message)}</p>}
        {['unknown', 'needs_credits'].includes(job.status) && <p className="hint">{tr("请先在 Suno.cn 核对作品或使用 Skill 的恢复流程；工作台不会自动再次提交。")}</p>}
        {result.tasks?.map((t: any, i: number) => <div className="music-result" key={i}><strong>{t.title || spec.title}</strong><small>{tr("服务状态：")}{String(t.status)} {t.duration ? tr("· {0} 秒", t.duration) : ''}</small>{t.fail_msg_show && <p>{t.fail_msg_show}</p>}{t.play_url && <a href={t.play_url} target="_blank" rel="noreferrer">{tr("打开生成音频")}<ExternalLink size={13}/></a>}{['success', '2'].includes(String(t.status)) && !job.outputs?.some((o: any) => o.serial_no === t.serial_no) && <><label className="check-row"><input type="checkbox" aria-label={tr("确认接入音轨 ") + t.serial_no} checked={audioAck === job.id + t.serial_no} onChange={e => setAudioAck(e.target.checked ? job.id + t.serial_no : '')}/>{tr("下载此已有音轨到项目，不重新生成或转换")}</label><button disabled={busy || audioAck !== job.id + t.serial_no} onClick={() => run(async () => { const r = await post(`/music/jobs/${job.id}/import`, { serial_no: t.serial_no, confirmed: true }); setAudioAck(''); setOperationId(r.id); })}>{tr("排队下载并纳入资产")}</button></>}</div>)}
        {job.outputs?.map((o: any) => <div className="music-result" key={o.asset_id}><strong>{tr("已接入项目资产 ·")}{o.serial_no}</strong><audio controls preload="none" src={`/api/assets/${o.asset_id}/file`}/><small>{tr("原始下载：")}{o.mime} · {o.duration.toFixed(1)} {tr("秒 · SHA-256")}{o.sha256}{tr("。上方试听当前资产版本，可能已编辑。")}</small></div>)}
      </section>;
    })}
    {operationState && <p role="status">{operationState}</p>}<button onClick={() => setPage('jobs')}>{tr("在作业中心查看进度、关联任务交付")}</button>
    <p className="hint">{tr("成功音轨可下载并校验登记为项目资产，不直接写入引擎。试听、检查和记录任务验收仍需另行完成。")}</p>
  </div>;
}
