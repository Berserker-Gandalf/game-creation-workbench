import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { api, post } from './api';

const labels: Record<string, string> = { found: tr("已发现 / 检查通过"), missing: tr("核心待处理"), optional_missing: tr("可选项未发现"), different: tr("需核对"), pending: tr("尚待检测") };

export default function Diagnostics({ run, busy, setPage, hasProject }: any) {
  const [report, setReport] = useState<any>(null), [error, setError] = useState('');
  useEffect(() => { let active = true; api('/diagnostics').then(v => { if (active) setReport(v); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  const load = (probe: boolean) => run(async () => { setError(''); setReport(probe ? await post('/diagnostics/check', { write_probe: true }) : await api('/diagnostics')); });
  return <div className="page-content diagnostics-page">
    <section className="card"><h2>{tr("先确认本机基础，再验证创作通道。")}</h2><p>{tr("本页检查程序、文件和工作台数据目录，不查询账户、不调用生成、不安装依赖。")}</p><div className="action-bar"><button className="secondary" disabled={busy} onClick={() => setPage('onboarding')}>{tr("打开快速上手与工具装配")}</button><button className="primary" disabled={busy} onClick={() => load(true)}>{tr("运行本机诊断（含数据写入检测）")}</button><button disabled={busy} onClick={() => load(false)}>{tr("仅刷新文件与版本信息")}</button></div><p className="hint">{tr("写入检测只在当前数据目录创建并删除本次临时文件，不修改项目资料。完整创作能力仍需在相应工作区验证。")}</p></section>
    {error && <p className="intake-warning">{error}<button onClick={() => load(false)}>{tr("重新读取诊断")}</button></p>}
    {!report ? <p>{tr("正在读取本机环境…")}</p> : <>
      <section className="card"><h2>{report.core_missing ? tr("有 {0} 项核心条件需处理", report.core_missing) : report.core_pending ? tr("基础文件已发现，{0} 项仍需核对或检测", report.core_pending) : tr("项目管理基础检查通过")}</h2><p>{serverText(report.note)}</p><small>{tr("检测时间：{0} · 写入检测：{1}", new Date(report.checked_at).toLocaleString(dateLocale), report.write_probe ? tr("包含") : tr("未进行"))}</small><details><summary>{tr("当前实例标识（本机信息）")}</summary><pre>{JSON.stringify(report.service, null, 2)}</pre></details></section>
      <div className="diagnostic-grid">{report.checks.map((item: any) => <section className="card" key={item.key}><div className="section-heading"><h3>{serverText(item.title)}</h3><span className={'status ' + (item.status === 'found' ? 'review' : 'blocked')}>{labels[item.status]}</span></div><p>{serverText(item.message)}</p><p className="hint">{serverText(item.action)}</p>{item.page !== 'diagnostics' && <button className="text-button" disabled={!hasProject && ['music', 'blender', 'management'].includes(item.page)} onClick={() => setPage(item.page)}>{tr("前往对应工作区")}{!hasProject && ['music', 'blender', 'management'].includes(item.page) ? tr("（先选择项目）") : ''}</button>}{Object.keys(item.details).length > 0 && <details><summary>{tr("路径与检测范围（本机信息）")}</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details>}</section>)}</div>
    </>}
  </div>;
}
