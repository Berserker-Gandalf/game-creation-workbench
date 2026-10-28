import { useEffect, useState } from 'react';
import { post } from './api';
import { serverText, t as tr } from './i18n';

export default function HardwareCheck({ root, run, busy }: any) {
  const [family, setFamily] = useState('sd15'), [download, setDownload] = useState(0), [report, setReport] = useState<any>(null);
  useEffect(() => setReport(null), [root]);
  const gib = (bytes: number) => (bytes / 1024 ** 3).toFixed(1) + ' GiB';
  return <section className="card hardware-check"><h2>{tr('WebUI 硬件预检')}</h2><p>{tr('读取本机硬件与所选目录的空间，不启动 WebUI、不运行工程代码，也不下载模型。')}</p>
    <div className="action-bar"><label>{tr('计划使用的模型基底')}<select aria-label={tr('预检模型基底')} value={family} onChange={e => { setFamily(e.target.value); setReport(null); }}><option value="sd15">SD 1.5</option><option value="sdxl">SDXL</option></select></label><label>{tr('计划新增下载量（GiB）')}<input aria-label={tr('计划新增下载量')} type="number" min="0" max="1000" value={download} onChange={e => { setDownload(Number(e.target.value)); setReport(null); }}/></label><button disabled={busy} onClick={() => run(async () => setReport(await post('/webui/preflight', { root, family, download_gib: download })))}>{tr('检查硬件与空间')}</button></div>
    {report && <div role="status"><div className="onboarding-tools"><p><strong>CPU</strong><span>{report.cpu} · {report.cpu_count || '?'}</span></p><p><strong>{tr('系统内存')}</strong><span>{report.ram ? gib(report.ram.total) + ' / ' + tr('当前可用') + ' ' + gib(report.ram.available) : tr('未能读取')}</span></p><p><strong>{tr('磁盘可用 / 预算')}</strong><span>{gib(report.disk.free)} / {gib(report.disk.required)}</span></p></div>{report.gpus.length ? report.gpus.map((gpu: any, i: number) => <p key={i}><strong>{gpu.name}</strong> · {gpu.vram === null ? tr('显存未知') : gib(gpu.vram)} · {tr('驱动')} {gpu.driver} <small>({gpu.source})</small></p>) : <p>{tr('未发现可核验的显卡信息')}</p>}{report.checks.map((check: any) => <p key={check.key}><strong>{check.status === 'ready' ? tr('达到建议值 / 文件已发现') : check.status === 'unknown' ? tr('待核验') : tr('需留意')}</strong> · {serverText(check.message)}</p>)}<p>{serverText(report.guidance)}</p><p>{tr('起步分辨率建议：')}{report.starting_size} × {report.starting_size}</p><a href={report.source} target="_blank" rel="noreferrer">{tr('WebUI 官方优化指引')} ↗</a></div>}
  </section>;
}
